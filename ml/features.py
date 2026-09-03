"""
ml/features.py
===============
Behavioral Feature Engineering — Table 4 of the thesis.

Implements the BehavioralFeatureEngine class that computes exactly 5 behavioral
features per transaction, using causal (no-lookahead) rolling user history.

Thesis Reference: Chapter 3, Section 3.3 — Behavioral Feature Engineering
                  Table 4 — Engineered Feature Definitions

FEATURES (5 total):
1. tx_freq_1h          — Transaction count by same user in rolling 1-hour window
2. tx_freq_24h         — Transaction count by same user in rolling 24-hour window
3. amount_deviation_z  — Z-score of current amount vs user's running mean/std
4. time_of_day_risk    — Binary: 1 if transaction between 00:00–05:00 (high-risk hours)
5. velocity_change     — Rate of change in amount across user's last 3 transactions
6. location_entropy    — Binary: 1 if device/region marker is new for this user

Note: 'location_entropy' uses a synthetic device/region marker derived from
      (synthetic_user_id + time_bucket) since the ULB dataset has no geo/device
      fields. This synthetic proxy is clearly labeled everywhere it appears.

Design Principles:
- CAUSAL ONLY: every computation uses ONLY past transactions relative to the
  current row's timestamp. No future data leaks in.
- O(1) AVERAGE LOOKUP: per-user state stored in dicts of deques/running stats.
- REUSABLE: same class instance is used identically during:
    a) offline training (ml/train.py augments the full dataset)
    b) live inference (backend/app/digital_twin.py wraps this class)
  This guarantees training-serving symmetry — no training/serving skew.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time as time_module
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WINDOW_1H_SECONDS: float = 3_600.0      # 1-hour rolling window
WINDOW_24H_SECONDS: float = 86_400.0    # 24-hour rolling window
VELOCITY_LOOKBACK: int = 3              # last N transactions for velocity
HIGH_RISK_HOUR_START: int = 0           # 00:00
HIGH_RISK_HOUR_END: int = 5             # 05:00 (exclusive: midnight to 4:59:59)
DATASET_EPOCH_SECONDS: float = 0.0     # ULB dataset Time starts at 0 seconds
SECONDS_PER_DAY: float = 86_400.0


def _time_to_hour_of_day(time_seconds: float) -> float:
    """
    Convert ULB dataset 'Time' (seconds since dataset start) to hour-of-day
    in [0, 24). The dataset spans ~2 days; we use modulo to wrap.
    """
    return (time_seconds % SECONDS_PER_DAY) / 3_600.0


# ---------------------------------------------------------------------------
# Per-user state container (stored in engine's in-memory dict)
# ---------------------------------------------------------------------------

@dataclass
class UserProfile:
    """
    Lightweight behavioral profile for one synthetic user.

    All fields are incrementally updated in O(1) per transaction.
    The profile is serializable to/from JSON for PostgreSQL persistence.
    """
    # Rolling timestamp log for frequency windows (max 24h of history)
    # Stored as deque; old entries pruned on each access
    tx_timestamps: deque = field(default_factory=lambda: deque(maxlen=10_000))

    # Running mean/variance for amount (Welford's online algorithm)
    amount_count: int = 0
    amount_mean: float = 0.0
    amount_M2: float = 0.0    # sum of squared deviations (Welford)

    # Last N amounts for velocity calculation
    recent_amounts: deque = field(default_factory=lambda: deque(maxlen=VELOCITY_LOOKBACK + 1))

    # Set of seen synthetic device markers
    seen_devices: set = field(default_factory=set)

    # Recent transactions (for Digital Twin profile view in the frontend)
    recent_transactions: deque = field(default_factory=lambda: deque(maxlen=50))

    # Total transaction count (for stats)
    total_tx_count: int = 0

    # Running risk score trend (exponential moving average of last scores)
    ema_risk_score: Optional[float] = None
    ema_alpha: float = 0.2

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict for PostgreSQL storage."""
        return {
            "tx_timestamps": list(self.tx_timestamps),
            "amount_count": self.amount_count,
            "amount_mean": self.amount_mean,
            "amount_M2": self.amount_M2,
            "recent_amounts": list(self.recent_amounts),
            "seen_devices": list(self.seen_devices),
            "recent_transactions": list(self.recent_transactions),
            "total_tx_count": self.total_tx_count,
            "ema_risk_score": self.ema_risk_score,
            "ema_alpha": self.ema_alpha,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        """Deserialize from dict (loaded from PostgreSQL)."""
        p = cls()
        p.tx_timestamps = deque(d.get("tx_timestamps", []), maxlen=10_000)
        p.amount_count = d.get("amount_count", 0)
        p.amount_mean = d.get("amount_mean", 0.0)
        p.amount_M2 = d.get("amount_M2", 0.0)
        p.recent_amounts = deque(d.get("recent_amounts", []), maxlen=VELOCITY_LOOKBACK + 1)
        p.seen_devices = set(d.get("seen_devices", []))
        p.recent_transactions = deque(d.get("recent_transactions", []), maxlen=50)
        p.total_tx_count = d.get("total_tx_count", 0)
        p.ema_risk_score = d.get("ema_risk_score")
        p.ema_alpha = d.get("ema_alpha", 0.2)
        return p

    @property
    def amount_variance(self) -> float:
        """Sample variance from Welford's running algorithm."""
        if self.amount_count < 2:
            return 0.0
        return self.amount_M2 / (self.amount_count - 1)

    @property
    def amount_std(self) -> float:
        """Sample standard deviation."""
        return math.sqrt(max(self.amount_variance, 0.0))

    def get_freq_in_window(self, current_time: float, window_seconds: float) -> int:
        """
        Count transactions strictly BEFORE current_time within the given window.
        Only counts past transactions — causal enforcement.
        """
        cutoff = current_time - window_seconds
        count = sum(1 for t in self.tx_timestamps if cutoff <= t < current_time)
        return count

    def prune_old_timestamps(self, current_time: float) -> None:
        """Remove timestamps older than 24h (saves memory; 24h is our largest window)."""
        cutoff = current_time - WINDOW_24H_SECONDS
        while self.tx_timestamps and self.tx_timestamps[0] < cutoff:
            self.tx_timestamps.popleft()

    def update_welford(self, new_amount: float) -> None:
        """
        Update running mean and variance using Welford's online algorithm.
        Called AFTER computing the current transaction's features (causal).
        """
        self.amount_count += 1
        delta = new_amount - self.amount_mean
        self.amount_mean += delta / self.amount_count
        delta2 = new_amount - self.amount_mean
        self.amount_M2 += delta * delta2

    def update_risk_ema(self, score: float) -> None:
        """Update exponential moving average of fraud risk score."""
        if self.ema_risk_score is None:
            self.ema_risk_score = score
        else:
            self.ema_risk_score = self.ema_alpha * score + (1 - self.ema_alpha) * self.ema_risk_score


# ---------------------------------------------------------------------------
# Main Engine Class
# ---------------------------------------------------------------------------

class BehavioralFeatureEngine:
    """
    Computes the 5 behavioral features from Table 4 of the thesis for each
    transaction, maintaining causal rolling history per synthetic user.

    Usage (same at training time and inference time):
        engine = BehavioralFeatureEngine()

        # For each transaction in chronological order:
        features = engine.compute_and_update(
            user_id="user_0042",
            timestamp=3602.5,       # ULB dataset Time field (seconds)
            amount=149.62,          # transaction amount (pre-scaling)
            device_marker="dev_A",  # synthetic device/region marker
        )
        # features is a dict with 5 keys (plus metadata)

    CRITICAL: Transactions must be processed in chronological order for
    causal correctness. The augment_dataset() function sorts by Time first.

    Thread Safety:
        Not thread-safe by default (single-threaded training context).
        In the backend, DigitalTwinEngine adds locking for concurrent access.
    """

    def __init__(self) -> None:
        # Per-user profile store: user_id (str) -> UserProfile
        self._profiles: Dict[str, UserProfile] = {}
        self._total_processed: int = 0

    def get_or_create_profile(self, user_id: str) -> UserProfile:
        """Return existing profile or create a new empty one."""
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile()
        return self._profiles[user_id]

    def load_profile(self, user_id: str, profile_dict: dict) -> None:
        """Load a serialized profile (from database) into the in-memory cache."""
        self._profiles[user_id] = UserProfile.from_dict(profile_dict)

    def get_profile_dict(self, user_id: str) -> Optional[dict]:
        """Get the serialized profile dict (for database persistence)."""
        if user_id not in self._profiles:
            return None
        return self._profiles[user_id].to_dict()

    def get_all_user_ids(self) -> List[str]:
        """Return list of all user IDs with profiles in memory."""
        return list(self._profiles.keys())

    def _generate_device_marker(self, user_id: str, timestamp: float) -> str:
        """
        Generate a deterministic synthetic device/region marker.

        SYNTHETIC PROXY: Since the ULB dataset has no device/geo fields,
        we derive a device marker from:
          hash(user_id + floor(timestamp / 86400)) mod 10
        This simulates a user having ~1-3 distinct 'devices' over time,
        with occasional new devices appearing (triggering entropy=1).

        In a real system this would be the actual device fingerprint or
        geolocation region code.
        """
        day_bin = int(timestamp // SECONDS_PER_DAY)
        # Give each user ~3 devices by hashing into a small pool
        device_pool_size = 3
        key = f"{user_id}_D{day_bin}"
        hash_int = int(hashlib.md5(key.encode()).hexdigest()[:4], 16)
        device_index = hash_int % device_pool_size
        return f"{user_id}_dev_{device_index}"

    # ------------------------------------------------------------------
    # Core method: compute features THEN update profile (causal order)
    # ------------------------------------------------------------------

    def compute_and_update(
        self,
        user_id: str,
        timestamp: float,
        amount: float,
        device_marker: Optional[str] = None,
        risk_score: Optional[float] = None,
        tx_metadata: Optional[dict] = None,
    ) -> dict:
        """
        Compute the 5 behavioral features for a single transaction, then
        update the user's profile with this transaction.

        CAUSAL ENFORCEMENT: Features are computed from the profile's state
        BEFORE this transaction is recorded. Only after feature computation
        is the profile updated. This ensures no lookahead.

        Args:
            user_id:       Synthetic (or real) user identifier
            timestamp:     Transaction time in seconds (ULB dataset 'Time' field,
                           or Unix epoch for live inference)
            amount:        Transaction amount (ORIGINAL, pre-scaling)
            device_marker: Device/region identifier. If None, a synthetic one
                           is generated (SYNTHETIC PROXY).
            risk_score:    Optional fraud score to update EMA risk trend.
            tx_metadata:   Optional dict for recent_transactions log.

        Returns:
            dict with keys:
                tx_freq_1h          (int)   — transactions in last 1 hour
                tx_freq_24h         (int)   — transactions in last 24 hours
                amount_deviation_z  (float) — z-score vs user history
                time_of_day_risk    (int)   — binary: 1 if midnight–5am
                velocity_change     (float) — amount change rate (last 3 tx)
                location_entropy    (int)   — binary: 1 if new device/region
        """
        profile = self.get_or_create_profile(user_id)

        # Generate device marker if not provided
        if device_marker is None:
            device_marker = self._generate_device_marker(user_id, timestamp)

        # ── Feature 1 & 2: Transaction Frequency (1h and 24h) ──────────
        # Prune timestamps older than 24h (keeps memory bounded)
        profile.prune_old_timestamps(timestamp)
        tx_freq_1h = profile.get_freq_in_window(timestamp, WINDOW_1H_SECONDS)
        tx_freq_24h = profile.get_freq_in_window(timestamp, WINDOW_24H_SECONDS)

        # ── Feature 3: Amount Deviation Z-Score ─────────────────────────
        if profile.amount_count >= 2 and profile.amount_std > 0:
            amount_deviation_z = (amount - profile.amount_mean) / profile.amount_std
        elif profile.amount_count >= 1:
            # Only 1 prior transaction: deviation is absolute difference
            amount_deviation_z = amount - profile.amount_mean
        else:
            # No history: z-score is 0 (no reference)
            amount_deviation_z = 0.0
        # Clip to [-10, 10] to prevent extreme outliers from dominating
        amount_deviation_z = float(np.clip(amount_deviation_z, -10.0, 10.0))

        # ── Feature 4: Time-of-Day Risk Flag ────────────────────────────
        hour_of_day = _time_to_hour_of_day(timestamp)
        time_of_day_risk = int(HIGH_RISK_HOUR_START <= hour_of_day < HIGH_RISK_HOUR_END)

        # ── Feature 5: Velocity Change Indicator ────────────────────────
        # Rate of change in amount across last 3 transactions
        recent = list(profile.recent_amounts)  # up to VELOCITY_LOOKBACK entries
        if len(recent) >= 2:
            # Linear regression slope approximation: last-minus-first / n
            velocity_change = (recent[-1] - recent[0]) / len(recent)
        elif len(recent) == 1:
            velocity_change = amount - recent[0]  # single step delta
        else:
            velocity_change = 0.0  # no history

        # ── Feature 6: Location/Device Entropy ──────────────────────────
        location_entropy = int(device_marker not in profile.seen_devices)

        # ── Assemble feature dict ────────────────────────────────────────
        features = {
            "tx_freq_1h": tx_freq_1h,
            "tx_freq_24h": tx_freq_24h,
            "amount_deviation_z": amount_deviation_z,
            "time_of_day_risk": time_of_day_risk,
            "velocity_change": velocity_change,
            "location_entropy": location_entropy,
        }

        # ─────────────────────────────────────────────────────────────────
        # UPDATE PROFILE (after feature computation — causal order)
        # ─────────────────────────────────────────────────────────────────
        profile.tx_timestamps.append(timestamp)
        profile.update_welford(amount)
        profile.recent_amounts.append(amount)
        profile.seen_devices.add(device_marker)
        profile.total_tx_count += 1

        if risk_score is not None:
            profile.update_risk_ema(risk_score)

        if tx_metadata is not None:
            tx_metadata["timestamp"] = timestamp
            tx_metadata["amount"] = amount
            tx_metadata["device_marker"] = device_marker
            tx_metadata["features"] = features
            profile.recent_transactions.append(tx_metadata)

        self._total_processed += 1
        return features

    # ------------------------------------------------------------------
    # Profile inspection (for Digital Twin API endpoint)
    # ------------------------------------------------------------------

    def get_profile_summary(self, user_id: str) -> Optional[dict]:
        """
        Return a comprehensive profile summary for the Digital Twin view.
        Returns None if user has no history.
        """
        if user_id not in self._profiles:
            return None
        p = self._profiles[user_id]
        return {
            "user_id": user_id,
            "total_transactions": p.total_tx_count,
            "amount_stats": {
                "count": p.amount_count,
                "mean": round(p.amount_mean, 4),
                "std": round(p.amount_std, 4),
            },
            "known_devices": list(p.seen_devices),
            "known_device_count": len(p.seen_devices),
            "recent_transactions": list(p.recent_transactions)[-10:],
            "current_risk_trend": round(p.ema_risk_score, 4) if p.ema_risk_score is not None else None,
            "last_24h_tx_count": len([
                t for t in p.tx_timestamps
                if (max(p.tx_timestamps) - t) <= WINDOW_24H_SECONDS
            ]) if p.tx_timestamps else 0,
        }

    def reset(self) -> None:
        """Clear all user profiles (for testing)."""
        self._profiles.clear()
        self._total_processed = 0


# ---------------------------------------------------------------------------
# Dataset Augmentation (used by training pipeline)
# ---------------------------------------------------------------------------

BEHAVIORAL_FEATURE_COLS = [
    "tx_freq_1h",
    "tx_freq_24h",
    "amount_deviation_z",
    "time_of_day_risk",
    "velocity_change",
    "location_entropy",
]


def augment_dataset(df: pd.DataFrame, amount_col: str = "Amount") -> pd.DataFrame:
    """
    Compute behavioral features for every row in the dataset and add them
    as new columns.

    CRITICAL: Rows must be processed in CHRONOLOGICAL order (sorted by 'Time')
    to ensure causal correctness. This function sorts by 'Time' before
    processing and restores the original index order afterwards.

    The 'Time' column used here is the ORIGINAL (pre-scaled) Time in seconds.
    If the DataFrame has already been scaled (Amount_scaled, Time_scaled),
    pass the original Amount values via amount_col='Amount' — which is still
    present in the parquet files as a column (scaling happens in-place but
    the original column is included before scaling is applied).

    NOTE: For the training pipeline, preprocessing.py saves the scaled
    Amount+Time but also preserves the original columns as the dataset
    already contains them. The scaler transforms in-place, so we need to
    be aware of what's in the parquet. Since preprocessing scales IN-PLACE,
    the parquet files have scaled Amount and Time. The BehavioralFeatureEngine
    uses ORIGINAL amounts for its running statistics (for interpretability),
    but the parquet only has scaled values.

    SOLUTION: We compute behavioral features BEFORE scaling in the pipeline,
    or we use the raw values from the training loader. See train.py for the
    correct calling order.

    Args:
        df: DataFrame with 'Time', amount_col, 'synthetic_user_id' columns
        amount_col: Name of the amount column (may be 'Amount' or the original)

    Returns:
        DataFrame with 6 new behavioral feature columns added.
    """
    if "synthetic_user_id" not in df.columns:
        raise ValueError(
            "DataFrame must have 'synthetic_user_id' column. "
            "Run preprocessing.add_synthetic_user_ids() first."
        )
    if "Time" not in df.columns and "time" not in df.columns:
        raise ValueError("DataFrame must have 'Time' column.")

    time_col = "Time" if "Time" in df.columns else "time"
    logger.info(
        "Augmenting dataset with behavioral features. Rows: %d, sorting by %s...",
        len(df), time_col,
    )

    # Sort by time for causal processing
    sort_idx = df[time_col].argsort()
    df_sorted = df.iloc[sort_idx].copy()

    engine = BehavioralFeatureEngine()
    feature_rows = []

    for _, row in df_sorted.iterrows():
        user_id = row["synthetic_user_id"]
        timestamp = float(row[time_col])
        amount = float(row[amount_col]) if amount_col in row.index else float(row.get("Amount", 0))

        features = engine.compute_and_update(
            user_id=user_id,
            timestamp=timestamp,
            amount=amount,
        )
        feature_rows.append(features)

    # Build feature DataFrame in sorted order
    feature_df = pd.DataFrame(feature_rows, index=df_sorted.index)

    # Join back to sorted df
    df_augmented = df_sorted.copy()
    for col in BEHAVIORAL_FEATURE_COLS:
        df_augmented[col] = feature_df[col]

    # Restore original row order
    df_augmented = df_augmented.loc[df.index].copy()

    logger.info(
        "Behavioral features computed. New columns: %s. Sample:\n%s",
        BEHAVIORAL_FEATURE_COLS,
        df_augmented[BEHAVIORAL_FEATURE_COLS].describe().round(4).to_string(),
    )
    return df_augmented


def get_feature_names_for_model() -> list:
    """
    Return the ordered list of feature column names used as model inputs.
    Must match exactly the feature order used during training.
    """
    pca_cols = [f"V{i}" for i in range(1, 29)]
    scaled_cols = ["Amount", "Time"]  # scaled versions
    return pca_cols + scaled_cols + BEHAVIORAL_FEATURE_COLS

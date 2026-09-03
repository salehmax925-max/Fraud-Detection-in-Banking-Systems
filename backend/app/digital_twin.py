"""
backend/app/digital_twin.py
=============================
Digital Twin Engine — Section 5 of the thesis

Operationalizes the thesis's Digital Twin concept (Section 2.3 / 3.9):
a continuously-updated lightweight behavioral profile per user, not a full
simulation twin — the thesis explicitly frames it this way to stay
computationally tractable.

Implementation:
  - Wraps ml.features.BehavioralFeatureEngine (SAME class used at training time)
    This guarantees training-serving symmetry — no feature skew.
  - In-memory dict cache for O(1) per-user profile lookup
  - PostgreSQL persistence so state survives backend restarts
  - Thread-safe with asyncio.Lock per user for concurrent request safety

Thesis Reference: Section 2.3, Section 3.9 — Digital Twin Engine
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

# Add project root to sys.path so ml/ is importable from backend
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.features import BehavioralFeatureEngine, UserProfile

logger = logging.getLogger(__name__)


class DigitalTwinEngine:
    """
    Live Digital Twin Engine — wraps BehavioralFeatureEngine with:
    1. In-memory per-user cache (same BehavioralFeatureEngine instance reused)
    2. PostgreSQL persistence (async, non-blocking)
    3. Per-user asyncio.Lock for concurrent access safety
    4. Profile loaded from DB on first access (cold start recovery)

    The BehavioralFeatureEngine is the SAME class used during training (ml/features.py),
    ensuring identical feature computation at training time and inference time.
    """

    def __init__(self) -> None:
        # Single BehavioralFeatureEngine instance — shared for all users
        # (same as at training time: one engine processes all rows in order)
        self._engine = BehavioralFeatureEngine()

        # Per-user asyncio lock to prevent concurrent profile corruption
        self._user_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        self._profiles_loaded: set = set()  # track which users loaded from DB
        logger.info("DigitalTwinEngine initialized.")

    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        """Get or create a per-user asyncio Lock."""
        async with self._global_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]

    async def _ensure_profile_loaded(self, user_id: str, db_session) -> None:
        """
        Load user profile from PostgreSQL if not already in memory.
        Called once per user per server lifetime (cold start recovery).
        """
        if user_id in self._profiles_loaded:
            return

        try:
            from sqlalchemy import select
            from app.models.orm import DigitalTwinProfile, Transaction

            result = await db_session.execute(
                select(DigitalTwinProfile).where(DigitalTwinProfile.synthetic_user_id == user_id)
            )
            db_profile = result.scalar_one_or_none()
            if db_profile and db_profile.rolling_stats:
                self._engine.load_profile(user_id, db_profile.rolling_stats)
                logger.debug("Loaded profile for user %s from DB.", user_id)
            else:
                # Reconstruct profile from user's historical transactions if available
                tx_result = await db_session.execute(
                    select(Transaction)
                    .where(Transaction.synthetic_user_id == user_id)
                    .order_by(Transaction.time_val.asc(), Transaction.created_at.asc())
                )
                txs = tx_result.scalars().all()
                if txs:
                    for tx in txs:
                        self._engine.compute_and_update(
                            user_id=user_id,
                            timestamp=float(tx.time_val),
                            amount=float(tx.amount),
                            device_marker=f"{user_id}_{int(tx.time_val // 3600)}",
                            risk_score=float(tx.final_score) if tx.final_score is not None else None,
                        )
                    try:
                        await self._persist_profile(user_id, db_session)
                    except Exception:
                        pass
                    logger.info("Reconstructed behavioral profile for user %s from %d transactions.", user_id, len(txs))
                else:
                    logger.debug("No DB profile or transactions for user %s.", user_id)

            self._profiles_loaded.add(user_id)
        except Exception as e:
            logger.warning("Failed to load profile from DB for user %s: %s", user_id, e)
            self._profiles_loaded.add(user_id)  # don't retry on error

    async def compute_features_and_update(
        self,
        user_id: str,
        timestamp: float,
        amount: float,
        device_marker: Optional[str] = None,
        risk_score: Optional[float] = None,
        tx_metadata: Optional[dict] = None,
        db_session=None,
    ) -> dict:
        """
        Compute behavioral features for a transaction, then update the profile.

        Steps:
        1. Acquire per-user lock
        2. Load profile from DB if not in memory (cold start)
        3. Compute 5 behavioral features (causal — uses ONLY past data)
        4. Update in-memory profile with this transaction
        5. Asynchronously persist updated profile to DB

        Args:
            user_id: Synthetic (or real) user identifier
            timestamp: Transaction time (seconds)
            amount: Transaction amount (original, pre-scaling)
            device_marker: Device/region marker (generated if None)
            risk_score: Optional fraud score for EMA risk trend
            tx_metadata: Optional dict stored in recent_transactions log
            db_session: Optional AsyncSession for DB persistence

        Returns:
            dict with 6 behavioral feature values
        """
        lock = await self._get_user_lock(user_id)
        async with lock:
            # Load from DB if first access
            if db_session is not None:
                await self._ensure_profile_loaded(user_id, db_session)

            # Compute features + update profile (in-memory, synchronous)
            features = self._engine.compute_and_update(
                user_id=user_id,
                timestamp=timestamp,
                amount=amount,
                device_marker=device_marker,
                risk_score=risk_score,
                tx_metadata=tx_metadata,
            )

            # Persist to DB (fire-and-forget — don't block the response)
            if db_session is not None:
                try:
                    await self._persist_profile(user_id, db_session)
                except Exception as e:
                    logger.warning("Failed to persist profile for user %s: %s", user_id, e)

        return features

    async def _persist_profile(self, user_id: str, db_session) -> None:
        """Save the current in-memory profile to PostgreSQL."""
        from sqlalchemy import select
        from app.models.orm import User, DigitalTwinProfile

        profile_dict = self._engine.get_profile_dict(user_id)
        if profile_dict is None:
            return

        # Get or create User record
        user_result = await db_session.execute(
            select(User).where(User.synthetic_user_id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            user = User(synthetic_user_id=user_id)
            db_session.add(user)
            await db_session.flush()  # get user.id

        # Get or create DigitalTwinProfile record
        dt_result = await db_session.execute(
            select(DigitalTwinProfile).where(DigitalTwinProfile.synthetic_user_id == user_id)
        )
        dt_profile = dt_result.scalar_one_or_none()

        if dt_profile is None:
            dt_profile = DigitalTwinProfile(
                user_id=user.id,
                synthetic_user_id=user_id,
                rolling_stats=profile_dict,
            )
            db_session.add(dt_profile)
        else:
            dt_profile.rolling_stats = profile_dict
            dt_profile.updated_at = datetime.now(timezone.utc)

        await db_session.flush()

    async def get_profile_summary(self, user_id: str, db_session=None) -> Optional[dict]:
        """
        Get behavioral profile summary for the Digital Twin API endpoint.
        Loads from DB if not in memory.
        """
        lock = await self._get_user_lock(user_id)
        async with lock:
            if db_session is not None:
                await self._ensure_profile_loaded(user_id, db_session)
            summary = self._engine.get_profile_summary(user_id)

        if summary is None:
            return None

        # Get updated_at from DB
        if db_session is not None:
            try:
                from sqlalchemy import select
                from app.models.orm import DigitalTwinProfile
                result = await db_session.execute(
                    select(DigitalTwinProfile.updated_at).where(
                        DigitalTwinProfile.synthetic_user_id == user_id
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    summary["updated_at"] = row.isoformat()
            except Exception:
                pass

        return summary

    def get_all_known_users(self) -> list:
        """Return list of user IDs with in-memory profiles."""
        return self._engine.get_all_user_ids()

    def reset_for_testing(self) -> None:
        """Clear all profiles (for unit testing only)."""
        self._engine.reset()
        self._profiles_loaded.clear()
        logger.warning("DigitalTwinEngine reset (testing only).")


# Singleton instance — shared across all API requests
_digital_twin_engine: Optional[DigitalTwinEngine] = None


def get_digital_twin_engine() -> DigitalTwinEngine:
    """FastAPI dependency: returns the singleton DigitalTwinEngine."""
    global _digital_twin_engine
    if _digital_twin_engine is None:
        _digital_twin_engine = DigitalTwinEngine()
    return _digital_twin_engine

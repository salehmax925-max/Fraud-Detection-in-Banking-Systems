"""
backend/app/services/csv_import_service.py
==========================================
CSV Data Import Service for FraudShield.

Implements the full ingestion pipeline:
  CSV Upload
    -> File Validation (extension, size, encoding)
    -> Schema Validation (required columns)
    -> Data Cleaning (nulls, types, ranges)
    -> Duplicate Handling
    -> Shared Preprocessing Pipeline (ml/preprocessing.py functions)
    -> Behavioral Feature Engineering (ml/features.py BehavioralFeatureEngine)
    -> Saved StandardScaler Transformation (scaler.joblib — NEVER fit new scaler)
    -> Feature Order Validation (against model_metadata.json)
    -> Optional Fraud Scoring (existing ScoringService)
    -> Database Import
    -> Import Summary

CRITICAL ARCHITECTURE PRINCIPLE:
  This service reuses the EXACT same preprocessing functions from ml/preprocessing.py
  and ml/features.py that were used during model training. There is ONE pipeline.
  scaler.transform() is always used, NEVER scaler.fit() or scaler.fit_transform().
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024   # 100 MB hard limit
MAX_ROW_COUNT: int       = 500_000              # reject absurdly large files
PREVIEW_ROWS: int        = 20                   # rows shown in data preview

# Required columns in uploaded CSV (raw ULB-style format)
_REQUIRED_RAW_COLS = (
    ["Time", "Amount"] + [f"V{i}" for i in range(1, 29)]
)

# ---------------------------------------------------------------------------
# Path resolution — find ml/ directory regardless of working directory
# ---------------------------------------------------------------------------

def _ml_dir() -> Path:
    """Return absolute path to the ml/ directory (sibling of backend/)."""
    here = Path(__file__).resolve()
    # backend/app/services/csv_import_service.py -> backend/app/services -> backend/app -> backend -> project root
    project_root = here.parent.parent.parent.parent
    ml = project_root / "ml"
    if not ml.exists():
        raise FileNotFoundError(f"ml/ directory not found at expected path: {ml}")
    return ml


def _add_ml_to_path() -> None:
    """Add project root and ml/ parent to sys.path so ml/ imports work."""
    ml = _ml_dir()
    project_root = str(ml.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


# ---------------------------------------------------------------------------
# Result dataclasses (plain dicts for JSON-serialisability)
# ---------------------------------------------------------------------------

class ValidationError:
    def __init__(self, row: Optional[int], column: Optional[str], message: str):
        self.row     = row
        self.column  = column
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {"row": self.row, "column": self.column, "message": self.message}


class ValidationResult:
    def __init__(self) -> None:
        self.valid:             bool                   = False
        self.file_size_bytes:   int                    = 0
        self.original_rows:     int                    = 0
        self.original_cols:     int                    = 0
        self.duplicate_rows:    int                    = 0
        self.missing_value_rows:int                    = 0
        self.invalid_rows:      int                    = 0
        self.valid_rows:        int                    = 0
        self.present_cols:      List[str]              = []
        self.missing_required:  List[str]              = []
        self.extra_cols:        List[str]              = []
        self.errors:            List[ValidationError]  = []
        self.warnings:          List[str]              = []
        self.preview:           List[Dict[str, Any]]   = []   # first N rows as dicts
        self.column_stats:      Dict[str, Any]         = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid":              self.valid,
            "file_size_bytes":    self.file_size_bytes,
            "original_rows":      self.original_rows,
            "original_cols":      self.original_cols,
            "duplicate_rows":     self.duplicate_rows,
            "missing_value_rows": self.missing_value_rows,
            "invalid_rows":       self.invalid_rows,
            "valid_rows":         self.valid_rows,
            "present_cols":       self.present_cols,
            "missing_required":   self.missing_required,
            "extra_cols":         self.extra_cols,
            "errors":             [e.to_dict() for e in self.errors],
            "warnings":           self.warnings,
            "preview":            self.preview,
            "column_stats":       self.column_stats,
        }


class ImportResult:
    def __init__(self) -> None:
        self.batch_id:            int                = 0
        self.original_rows:       int                = 0
        self.duplicate_rows:      int                = 0
        self.invalid_rows:        int                = 0
        self.valid_rows:          int                = 0
        self.imported_rows:       int                = 0
        self.behavioral_features: int                = 6
        self.model_features:      int                = 36
        self.scored:              bool               = False
        self.approve_count:       Optional[int]      = None
        self.review_count:        Optional[int]      = None
        self.block_count:         Optional[int]      = None
        self.processing_time_ms:  int                = 0
        self.errors:              List[Dict]         = []
        self.warnings:            List[str]          = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id":            self.batch_id,
            "original_rows":       self.original_rows,
            "duplicate_rows":      self.duplicate_rows,
            "invalid_rows":        self.invalid_rows,
            "valid_rows":          self.valid_rows,
            "imported_rows":       self.imported_rows,
            "behavioral_features": self.behavioral_features,
            "model_features":      self.model_features,
            "scored":              self.scored,
            "approve_count":       self.approve_count,
            "review_count":        self.review_count,
            "block_count":         self.block_count,
            "processing_time_ms":  self.processing_time_ms,
            "errors":              self.errors,
            "warnings":            self.warnings,
        }


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------

class CsvImportService:
    """
    Encapsulates the full CSV ingestion pipeline.

    Reuses ml/preprocessing.py and ml/features.py — the SAME code used
    during model training. This guarantees training-serving consistency.
    """

    def __init__(self) -> None:
        _add_ml_to_path()
        self._scaler      = None   # loaded lazily from scaler.joblib
        self._metadata    = None   # loaded lazily from model_metadata.json
        self._model_dir   = None

    def _get_model_dir(self) -> Path:
        if self._model_dir is None:
            ml = _ml_dir()
            # model artifacts live in project_root/models/
            self._model_dir = ml.parent / "models"
        return self._model_dir

    def _load_scaler(self):
        """Load the saved StandardScaler from scaler.joblib. NEVER fit a new one."""
        if self._scaler is None:
            import joblib
            scaler_path = self._get_model_dir() / "scaler.joblib"
            if not scaler_path.exists():
                raise FileNotFoundError(f"scaler.joblib not found at {scaler_path}")
            self._scaler = joblib.load(scaler_path)
            logger.info("Loaded scaler from %s", scaler_path)
        return self._scaler

    def _load_metadata(self) -> dict:
        """Load model_metadata.json to get expected feature names and order."""
        if self._metadata is None:
            meta_path = self._get_model_dir() / "model_metadata.json"
            if not meta_path.exists():
                raise FileNotFoundError(f"model_metadata.json not found at {meta_path}")
            with open(meta_path, encoding="utf-8") as f:
                self._metadata = json.load(f)
            logger.info("Loaded model metadata from %s", meta_path)
        return self._metadata

    # -----------------------------------------------------------------------
    # Step 1: File-level validation
    # -----------------------------------------------------------------------

    def validate_file(
        self,
        file_bytes: bytes,
        original_filename: str,
    ) -> ValidationResult:
        """
        Full validation pipeline:
          1. File size check
          2. Extension check
          3. Encoding check
          4. Parse CSV
          5. Schema validation
          6. Type/range sanity checks
          7. Duplicate detection
          8. Missing value report
          9. Build preview
        Returns a ValidationResult — does NOT write to database.
        """
        result = ValidationResult()
        result.file_size_bytes = len(file_bytes)

        # 1. Size check
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            result.errors.append(ValidationError(
                None, None,
                f"File too large: {len(file_bytes) / 1024 / 1024:.1f} MB. Maximum allowed: 100 MB."
            ))
            return result

        if len(file_bytes) == 0:
            result.errors.append(ValidationError(None, None, "File is empty."))
            return result

        # 2. Extension check
        ext = Path(original_filename).suffix.lower()
        if ext != ".csv":
            result.errors.append(ValidationError(
                None, None,
                f"Invalid file type '{ext}'. Only CSV files are supported."
            ))
            return result

        # 3. Encoding / parse
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = file_bytes.decode("latin-1")
                result.warnings.append("File was not UTF-8 encoded; latin-1 decoding was used.")
            except Exception:
                result.errors.append(ValidationError(None, None, "File encoding is not readable. Use UTF-8 or Latin-1."))
                return result

        # 4. Parse CSV — auto-detect separator (comma or semicolon)
        # Windows/Excel with Arabic or European regional settings exports semicolon-separated CSVs
        try:
            first_line = text.split("\n")[0] if "\n" in text else text
            sep = ";" if first_line.count(";") > first_line.count(",") else ","
            df = pd.read_csv(io.StringIO(text), sep=sep)
            if sep == ";":
                result.warnings.append(
                    "Detected semicolon-separated file (Excel regional format). Parsed successfully."
                )
        except Exception as e:
            result.errors.append(ValidationError(None, None, f"Could not parse CSV: {e}"))
            return result

        if len(df) == 0:
            result.errors.append(ValidationError(None, None, "CSV file contains no data rows."))
            return result

        if len(df) > MAX_ROW_COUNT:
            result.errors.append(ValidationError(
                None, None,
                f"CSV contains {len(df):,} rows, which exceeds the maximum of {MAX_ROW_COUNT:,}."
            ))
            return result

        result.original_rows = len(df)
        result.original_cols = len(df.columns)
        result.present_cols  = list(df.columns)

        # 5. Schema validation
        missing = [c for c in _REQUIRED_RAW_COLS if c not in df.columns]
        extra   = [c for c in df.columns if c not in _REQUIRED_RAW_COLS and c not in ("Class",)]
        result.missing_required = missing
        result.extra_cols       = extra

        if missing:
            result.errors.append(ValidationError(
                None, None,
                f"Missing required columns: {', '.join(missing)}"
            ))
            return result  # Cannot continue without required columns

        if extra:
            result.warnings.append(
                f"Extra columns will be ignored during import: {', '.join(extra)}"
            )

        # 6. Type / range checks
        row_errors: Dict[int, List[str]] = {}

        # Numeric conversion for all required cols
        numeric_cols = _REQUIRED_RAW_COLS
        for col in numeric_cols:
            non_numeric_mask = pd.to_numeric(df[col], errors="coerce").isna() & df[col].notna()
            for idx in df[non_numeric_mask].index:
                row_errors.setdefault(idx, []).append(f"Column '{col}' has non-numeric value: '{df.at[idx, col]}'")

        # Amount >= 0
        amount_numeric = pd.to_numeric(df["Amount"], errors="coerce")
        neg_mask = amount_numeric < 0
        for idx in df[neg_mask].index:
            row_errors.setdefault(idx, []).append(f"Amount must be >= 0, got {df.at[idx, 'Amount']}")

        # V-features: finite values
        for col in [f"V{i}" for i in range(1, 29)]:
            vals = pd.to_numeric(df[col], errors="coerce")
            inf_mask = np.isinf(vals.fillna(0))
            for idx in df[inf_mask].index:
                row_errors.setdefault(idx, []).append(f"Column '{col}' contains infinite value")

        # Collect errors
        for idx, msgs in row_errors.items():
            for msg in msgs:
                result.errors.append(ValidationError(int(idx) + 2, None, msg))  # +2 = header row + 1-indexed

        result.invalid_rows = len(row_errors)

        # 7. Duplicates
        dup_mask = df.duplicated(subset=_REQUIRED_RAW_COLS, keep="first")
        result.duplicate_rows = int(dup_mask.sum())

        # 8. Missing values
        null_mask = df[_REQUIRED_RAW_COLS].isnull().any(axis=1)
        result.missing_value_rows = int(null_mask.sum())

        # Valid rows = original - invalid - duplicates - missing
        invalid_indices = set(row_errors.keys()) | set(df[null_mask].index)
        result.valid_rows = len(df) - len(invalid_indices) - result.duplicate_rows

        # 9. Preview (first PREVIEW_ROWS rows)
        preview_df = df.head(PREVIEW_ROWS).copy()
        # Round floats for readability
        for col in preview_df.select_dtypes(include=[float]).columns:
            preview_df[col] = preview_df[col].round(4)
        result.preview = preview_df.to_dict(orient="records")

        # Column stats
        result.column_stats = {
            col: {
                "min":    float(df[col].min()) if col in df.columns else None,
                "max":    float(df[col].max()) if col in df.columns else None,
                "mean":   round(float(df[col].mean()), 4) if col in df.columns else None,
                "nulls":  int(df[col].isnull().sum()) if col in df.columns else None,
            }
            for col in ["Time", "Amount"]
        }

        result.valid = len(result.errors) == 0 or result.valid_rows > 0
        return result

    # -----------------------------------------------------------------------
    # Step 2: Preprocessing (shared pipeline)
    # -----------------------------------------------------------------------

    def preprocess_dataframe(
        self,
        df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, Dict[str, Any], List[Dict]]:
        """
        Apply the EXACT same preprocessing pipeline used during model training.

        Reuses:
          - ml/preprocessing.py: remove_duplicates, sanity_checks,
            add_synthetic_user_ids, SCALED_COLS
          - ml/features.py: BehavioralFeatureEngine.compute_and_update()
          - scaler.joblib: loaded via _load_scaler() — NEVER fit_transform

        Returns:
          processed_df: DataFrame with all 36 model features in correct order
          report: stats dict (rows, duplicates removed, etc.)
          row_errors: list of {row, reason} for rejected rows
        """
        from ml.preprocessing import (
            remove_duplicates,
            sanity_checks,
            add_synthetic_user_ids,
            SCALED_COLS,
            generate_synthetic_user_id,
        )
        from ml.features import BehavioralFeatureEngine

        report: Dict[str, Any] = {}
        row_errors: List[Dict] = []

        # Keep only needed columns (ignore Class if present, ignore extras)
        keep_cols = [c for c in _REQUIRED_RAW_COLS if c in df.columns]
        if "Class" in df.columns:
            keep_cols.append("Class")
        df = df[keep_cols].copy()

        # If Class is missing, add dummy (not used for scoring)
        if "Class" not in df.columns:
            df["Class"] = 0

        # Coerce numeric types
        for col in _REQUIRED_RAW_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop rows with any NaN in required columns
        before = len(df)
        df.dropna(subset=_REQUIRED_RAW_COLS, inplace=True)
        null_dropped = before - len(df)
        if null_dropped:
            report["null_rows_dropped"] = null_dropped
            row_errors.extend([
                {"row": None, "reason": f"{null_dropped} rows dropped due to missing values in required columns"}
            ])

        # Remove duplicates (reusing ml/preprocessing.py function)
        df, report = remove_duplicates(df, report)

        # Sanity checks (reusing ml/preprocessing.py function)
        df, report = sanity_checks(df, report)

        if len(df) == 0:
            return pd.DataFrame(), report, row_errors

        # Sort by Time (causal requirement for behavioral features)
        df = df.sort_values("Time").reset_index(drop=True)

        # Add synthetic user IDs (reusing ml/preprocessing.py function)
        df = add_synthetic_user_ids(df)

        # Behavioral Feature Engineering — reusing ml/features.py BehavioralFeatureEngine
        engine = BehavioralFeatureEngine()
        behavioral_records = []
        for _, row in df.iterrows():
            device_marker = f"{row['synthetic_user_id']}_{int(row['Time'] // 3600)}"
            feats = engine.compute_and_update(
                user_id=row["synthetic_user_id"],
                timestamp=float(row["Time"]),
                amount=float(row["Amount"]),
                device_marker=device_marker,
            )
            behavioral_records.append(feats)

        behavioral_df = pd.DataFrame(behavioral_records, index=df.index)
        df = pd.concat([df, behavioral_df], axis=1)

        # StandardScaler — ONLY transform(), NEVER fit() or fit_transform()
        scaler = self._load_scaler()
        df[SCALED_COLS] = scaler.transform(df[SCALED_COLS])
        logger.info("Applied saved StandardScaler.transform() to %s columns", SCALED_COLS)

        user_col = df["synthetic_user_id"].copy() if "synthetic_user_id" in df.columns else None

        # Feature ordering: must exactly match model training order
        metadata = self._load_metadata()
        expected_features = metadata.get("feature_names", [])

        if expected_features:
            missing_feats = [f for f in expected_features if f not in df.columns]
            if missing_feats:
                logger.warning("Missing model features after preprocessing: %s", missing_feats)
                for f in missing_feats:
                    df[f] = 0.0  # fill with zero, mark as warning
                report["missing_model_features"] = missing_feats

            df = df[expected_features]
            logger.info("Feature order validated: %d features in correct order", len(expected_features))
        else:
            # Fallback: use known feature order
            v_cols    = [f"V{i}" for i in range(1, 29)]
            base_cols = v_cols + ["Amount", "Time"]
            beh_cols  = ["tx_freq_1h", "tx_freq_24h", "amount_deviation_z",
                         "time_of_day_risk", "velocity_change", "location_entropy"]
            all_feats = [c for c in base_cols + beh_cols if c in df.columns]
            df = df[all_feats]

        if user_col is not None:
            df["synthetic_user_id"] = user_col

        report["final_rows"]     = len(df)
        report["final_features"] = len([c for c in df.columns if c != "synthetic_user_id"])

        return df, report, row_errors

    # -----------------------------------------------------------------------
    # Step 3: Persist to database with real scoring + SHAP
    # -----------------------------------------------------------------------

    async def import_to_db(
        self,
        session,
        raw_df: pd.DataFrame,
        processed_df: pd.DataFrame,
        scoring_service,           # ScoringService singleton — None to skip scoring
        batch_id: Optional[int],   # ImportBatch.id to stamp on each row
    ) -> int:
        """
        Insert valid processed rows into the transactions table.

        Fixes vs old implementation:
          - Reads synthetic_user_id from processed_df (not raw_df)
          - Aligns raw/processed rows by shared Time-based sort (both sorted before call)
          - Uses real ScoringService for scoring — same as live transactions
          - Computes + stores SHAP explanations per row
          - Stamps import_batch_id for bulk-delete support

        Returns count of rows actually inserted.
        """
        from app.models.orm import User, Transaction, ShapExplanation
        from sqlalchemy import select as sa_select

        # Build the behavioral feature column names present in processed_df
        beh_cols = ["tx_freq_1h", "tx_freq_24h", "amount_deviation_z",
                    "time_of_day_risk", "velocity_change", "location_entropy"]

        imported = 0

        for i in range(len(processed_df)):
            try:
                proc_row = processed_df.iloc[i]
                raw_row  = raw_df.iloc[i]

                # ── Correct user ID: from processed_df (has synthetic_user_id column) ──
                if "synthetic_user_id" in processed_df.columns:
                    syn_uid = str(proc_row["synthetic_user_id"])
                elif "synthetic_user_id" in raw_df.columns:
                    syn_uid = str(raw_row["synthetic_user_id"])
                else:
                    syn_uid = f"user_import_{i:06d}"

                # ── Resolve / create user ──
                result = await session.execute(
                    sa_select(User).where(User.synthetic_user_id == syn_uid)
                )
                user = result.scalar_one_or_none()
                if user is None:
                    user = User(synthetic_user_id=syn_uid)
                    session.add(user)
                    await session.flush()

                # ── Raw PCA features ──
                v_feats = {f"V{j}": float(raw_row.get(f"V{j}", 0.0)) for j in range(1, 29)}

                # ── Score using real ScoringService ──
                score_result = None
                feature_vector = None
                if scoring_service is not None:
                    try:
                        v_list    = [float(raw_row.get(f"V{j}", 0.0)) for j in range(1, 29)]
                        beh_dict  = {
                            col: float(proc_row[col])
                            for col in beh_cols
                            if col in proc_row.index
                        }
                        amount    = float(raw_row.get("Amount", 0.0))
                        time_val  = float(raw_row.get("Time", 0.0))

                        score_result   = scoring_service.score_transaction(
                            v_features=v_list,
                            amount=amount,
                            time_val=time_val,
                            behavioral_features=beh_dict,
                        )
                        feature_vector = score_result.get("feature_vector")
                    except Exception as exc:
                        logger.warning("Scoring failed for row %d: %s", i, exc)

                # ── Build Transaction ORM object ──
                tx = Transaction(
                    user_id=user.id,
                    synthetic_user_id=syn_uid,
                    time_val=float(raw_row.get("Time", 0)),
                    amount=float(raw_row.get("Amount", 0)),
                    v_features=v_feats,
                    tx_freq_1h=float(proc_row["tx_freq_1h"]) if "tx_freq_1h" in proc_row.index else None,
                    tx_freq_24h=float(proc_row["tx_freq_24h"]) if "tx_freq_24h" in proc_row.index else None,
                    amount_deviation_z=float(proc_row["amount_deviation_z"]) if "amount_deviation_z" in proc_row.index else None,
                    time_of_day_risk=int(proc_row["time_of_day_risk"]) if "time_of_day_risk" in proc_row.index else None,
                    velocity_change=float(proc_row["velocity_change"]) if "velocity_change" in proc_row.index else None,
                    location_entropy=int(proc_row["location_entropy"]) if "location_entropy" in proc_row.index else None,
                    xgb_score=score_result["xgb_score"] if score_result else None,
                    if_score=score_result["if_score"] if score_result else None,
                    final_score=score_result["final_score"] if score_result else None,
                    decision_tier=score_result["decision_tier"] if score_result else None,
                    is_simulation=False,
                    import_batch_id=batch_id,
                    true_label=(
                        int(raw_row["Class"])
                        if "Class" in raw_row.index and raw_row.get("Class") is not None
                           and not pd.isna(raw_row.get("Class"))
                        else None
                    ),
                )
                session.add(tx)
                await session.flush()   # flush to get tx.id

                # ── Compute + persist SHAP explanations ──
                if scoring_service is not None and feature_vector is not None:
                    try:
                        import numpy as np
                        fv_np  = np.array(feature_vector, dtype=np.float64)
                        contribs = scoring_service.get_shap_explanation(fv_np, top_n=10)
                        for contrib in contribs:
                            shap_row = ShapExplanation(
                                transaction_id=tx.id,
                                feature_name=contrib["feature_name"],
                                shap_value=contrib["shap_value"],
                                feature_value=contrib["feature_value"],
                                direction=contrib["direction"],
                                rank=contrib["rank"],
                            )
                            session.add(shap_row)
                    except Exception as exc:
                        logger.warning("SHAP failed for row %d: %s", i, exc)

                imported += 1

            except Exception as exc:
                logger.warning("Failed to insert row %d: %s", i, exc)
                continue

        await session.flush()
        logger.info("import_to_db: inserted %d / %d rows", imported, len(processed_df))
        return imported


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_service: Optional[CsvImportService] = None


def get_csv_import_service() -> CsvImportService:
    global _service
    if _service is None:
        _service = CsvImportService()
    return _service

"""
backend/app/api/data_import_routes.py
=======================================
CSV Data Import API endpoints.

Endpoints:
  POST /api/data-import/validate    — validate CSV, return report (no DB write)
  POST /api/data-import             — validate + import (+ optional scoring)
  GET  /api/data-import/history     — list past import batches

Security:
  - Requires authenticated user (JWT cookie)
  - Admin role required for all endpoints
  - File size validated server-side (100 MB max)
  - Only .csv extension accepted
  - UUID-based server filenames (original filename never used as path)
"""
from __future__ import annotations

import io
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.auth import AuthUser, SystemLog
from app.models.orm import ImportBatch, Transaction
from app.services.csv_import_service import get_csv_import_service
from app.services.scoring import get_scoring_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data-import", tags=["Data Import"])

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ValidationErrorItem(BaseModel):
    row: Optional[int]
    column: Optional[str]
    message: str


class ColumnStats(BaseModel):
    min: Optional[float]
    max: Optional[float]
    mean: Optional[float]
    nulls: Optional[int]


class ValidateResponse(BaseModel):
    valid: bool
    file_size_bytes: int
    original_rows: int
    original_cols: int
    duplicate_rows: int
    missing_value_rows: int
    invalid_rows: int
    valid_rows: int
    present_cols: List[str]
    missing_required: List[str]
    extra_cols: List[str]
    errors: List[ValidationErrorItem]
    warnings: List[str]
    preview: List[dict]
    column_stats: dict


class ImportResponse(BaseModel):
    batch_id: int
    original_rows: int
    duplicate_rows: int
    invalid_rows: int
    valid_rows: int
    imported_rows: int
    behavioral_features: int
    model_features: int
    scored: bool
    approve_count: Optional[int]
    review_count: Optional[int]
    block_count: Optional[int]
    processing_time_ms: int
    errors: List[dict]
    warnings: List[str]


class ImportBatchSummary(BaseModel):
    id: int
    original_filename: str
    uploaded_by_username: str
    uploaded_by_display_name: str
    original_rows: int
    valid_rows: int
    imported_rows: int
    duplicate_rows: int
    invalid_rows: int
    scored: bool
    approve_count: Optional[int]
    review_count: Optional[int]
    block_count: Optional[int]
    mode: str
    status: str
    processing_time_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Helper: log import event to system_logs
# ---------------------------------------------------------------------------

async def _log_import_event(
    db: AsyncSession,
    event_type: str,
    user: AuthUser,
    description: str,
    metadata: Optional[dict] = None,
    log_level: str = "INFO",
) -> None:
    log = SystemLog(
        log_level=log_level,
        event_type=event_type,
        username=user.username,
        display_name=user.display_name,
        description=description,
        extra_data=metadata,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
    await db.flush()


# ---------------------------------------------------------------------------
# POST /api/data-import/validate
# ---------------------------------------------------------------------------

@router.post(
    "/validate",
    response_model=ValidateResponse,
    summary="Validate a CSV file without importing",
)
async def validate_csv(
    file: UploadFile = File(...),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ValidateResponse:
    """
    Validate a CSV file and return a detailed compatibility report.
    Does NOT write any data to the database.
    Requires admin role.
    """
    # Read file bytes
    file_bytes = await file.read()
    original_filename = file.filename or "upload.csv"

    await _log_import_event(
        db, "DATA_IMPORT_VALIDATE_STARTED", current_user,
        f"Validation started: {original_filename} ({len(file_bytes)} bytes)",
        {"filename": original_filename, "size_bytes": len(file_bytes)},
    )

    service = get_csv_import_service()
    result  = service.validate_file(file_bytes, original_filename)

    await _log_import_event(
        db, "DATA_IMPORT_VALIDATED", current_user,
        f"Validation complete: {original_filename} — valid={result.valid}, rows={result.original_rows}",
        {"filename": original_filename, "valid": result.valid, "rows": result.original_rows},
    )
    await db.commit()

    return ValidateResponse(
        valid=result.valid,
        file_size_bytes=result.file_size_bytes,
        original_rows=result.original_rows,
        original_cols=result.original_cols,
        duplicate_rows=result.duplicate_rows,
        missing_value_rows=result.missing_value_rows,
        invalid_rows=result.invalid_rows,
        valid_rows=result.valid_rows,
        present_cols=result.present_cols,
        missing_required=result.missing_required,
        extra_cols=result.extra_cols,
        errors=[ValidationErrorItem(**e) for e in [e.to_dict() for e in result.errors]],
        warnings=result.warnings,
        preview=result.preview,
        column_stats=result.column_stats,
    )


# ---------------------------------------------------------------------------
# POST /api/data-import
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ImportResponse,
    summary="Import CSV data into the system",
)
async def import_csv(
    file: UploadFile = File(...),
    score: str = Form(default="false"),   # "true" or "false"
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ImportResponse:
    """
    Full CSV import pipeline:
      1. Validate file
      2. Preprocess using shared training pipeline
      3. Optionally score with existing fraud model
      4. Import to transactions table
      5. Record batch metadata in import_batches

    Requires admin role.
    CSV data passes through the EXACT same preprocessing used during training.
    scaler.transform() is used — NEVER scaler.fit() or fit_transform().
    """
    t_start = time.time()

    file_bytes = await file.read()
    original_filename = file.filename or "upload.csv"
    should_score = score.lower() == "true"
    server_filename = f"{uuid.uuid4()}.csv"
    mode = "import_and_score" if should_score else "import"

    await _log_import_event(
        db, "DATA_IMPORT_STARTED", current_user,
        f"Import started: {original_filename} ({len(file_bytes)} bytes), score={should_score}",
        {"filename": original_filename, "size_bytes": len(file_bytes), "score": should_score},
    )

    service = get_csv_import_service()

    # --- Validate ---
    val_result = service.validate_file(file_bytes, original_filename)

    if not val_result.valid or val_result.valid_rows == 0:
        # Create a failed batch record
        batch = ImportBatch(
            original_filename=original_filename,
            server_filename=server_filename,
            uploaded_by_username=current_user.username,
            uploaded_by_display_name=current_user.display_name,
            original_rows=val_result.original_rows,
            duplicate_rows=val_result.duplicate_rows,
            invalid_rows=val_result.invalid_rows,
            valid_rows=0,
            imported_rows=0,
            mode=mode,
            status="failed",
            error_message="; ".join(e.message for e in val_result.errors[:5]),
            processing_time_ms=int((time.time() - t_start) * 1000),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(batch)
        await db.flush()
        await db.commit()

        await _log_import_event(
            db, "DATA_IMPORT_FAILED", current_user,
            f"Import failed validation: {original_filename}",
            {"filename": original_filename, "errors": [e.to_dict() for e in val_result.errors[:5]]},
            log_level="WARNING",
        )
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "CSV validation failed. No data was imported.",
                "errors": [e.to_dict() for e in val_result.errors],
                "missing_required": val_result.missing_required,
            },
        )

    # --- Parse & preprocess ---
    try:
        text = file_bytes.decode("utf-8", errors="replace")
        # Auto-detect separator: semicolon (Excel/regional) or comma
        first_line = text.split("\n")[0] if "\n" in text else text
        sep = ";" if first_line.count(";") > first_line.count(",") else ","
        raw_df = pd.read_csv(io.StringIO(text), sep=sep)

        processed_df, prep_report, row_errors = service.preprocess_dataframe(raw_df.copy())
    except Exception as exc:
        logger.error("Preprocessing failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preprocessing failed: {exc}",
        )

    if len(processed_df) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="After preprocessing, no valid rows remained. Check the CSV format.",
        )

    # --- Always score using the real ScoringService singleton ---
    # This is the exact same service used for live transaction scoring,
    # guaranteeing training-serving consistency + SHAP explanations.
    scoring_svc = None
    approve_count = review_count = block_count = None
    try:
        scoring_svc = get_scoring_service()
    except Exception as exc:
        logger.warning("ScoringService unavailable — importing without scores: %s", exc)
        val_result.warnings.append(f"Model not loaded — transactions imported without scores: {exc}")

    # --- Create the batch record first (we need batch.id to stamp on transactions) ---
    t_ms_pre = int((time.time() - t_start) * 1000)
    batch = ImportBatch(
        original_filename=original_filename,
        server_filename=server_filename,
        uploaded_by_username=current_user.username,
        uploaded_by_display_name=current_user.display_name,
        original_rows=val_result.original_rows,
        duplicate_rows=val_result.duplicate_rows,
        invalid_rows=val_result.invalid_rows,
        valid_rows=val_result.valid_rows,
        imported_rows=0,   # will be updated below
        scored=scoring_svc is not None,
        mode=mode,
        status="importing",
        processing_time_ms=None,
        completed_at=None,
    )
    db.add(batch)
    await db.flush()   # get batch.id
    batch_id = batch.id

    # --- Align raw_df with processed_df (both sorted by Time in preprocess_dataframe) ---
    # processed_df may have fewer rows after dedup/sanity; slice raw_df to same length
    raw_df_sorted = raw_df.sort_values("Time").reset_index(drop=True)
    raw_aligned   = raw_df_sorted.iloc[:len(processed_df)].reset_index(drop=True)

    # --- Import to DB (scoring + SHAP happen per-row inside import_to_db) ---
    imported = await service.import_to_db(
        session=db,
        raw_df=raw_aligned,
        processed_df=processed_df,
        scoring_service=scoring_svc,
        batch_id=batch_id,
    )

    # --- Tally decision tiers from DB ---
    if scoring_svc is not None:
        from sqlalchemy import func as sqlfunc
        tier_result = await db.execute(
            select(Transaction.decision_tier, sqlfunc.count(Transaction.id))
            .where(Transaction.import_batch_id == batch_id)
            .group_by(Transaction.decision_tier)
        )
        tier_counts = {row[0]: row[1] for row in tier_result}
        approve_count = tier_counts.get("APPROVE", 0)
        review_count  = tier_counts.get("REVIEW", 0)
        block_count   = tier_counts.get("BLOCK", 0)

    t_ms = int((time.time() - t_start) * 1000)

    # --- Update the batch record with final stats ---
    batch.imported_rows      = imported
    batch.approve_count      = approve_count
    batch.review_count       = review_count
    batch.block_count        = block_count
    batch.status             = "completed"
    batch.processing_time_ms = t_ms
    batch.completed_at       = datetime.now(timezone.utc)
    await db.flush()

    await _log_import_event(
        db, "DATA_IMPORT_COMPLETED", current_user,
        f"Import completed: {original_filename} — {imported} rows imported in {t_ms}ms",
        {
            "filename": original_filename,
            "imported": imported,
            "scored": scoring_svc is not None,
            "approve": approve_count,
            "review": review_count,
            "block": block_count,
        },
    )
    await db.commit()

    meta = service._load_metadata()
    feature_count = len(meta.get("feature_names", [])) or 36

    return ImportResponse(
        batch_id=batch_id,
        original_rows=val_result.original_rows,
        duplicate_rows=val_result.duplicate_rows,
        invalid_rows=val_result.invalid_rows,
        valid_rows=val_result.valid_rows,
        imported_rows=imported,
        behavioral_features=6,
        model_features=feature_count,
        scored=scoring_svc is not None,
        approve_count=approve_count,
        review_count=review_count,
        block_count=block_count,
        processing_time_ms=t_ms,
        errors=row_errors,
        warnings=val_result.warnings,
    )


# ---------------------------------------------------------------------------
# GET /api/data-import/history
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=List[ImportBatchSummary],
    summary="List past CSV import batches",
)
async def get_import_history(
    limit: int = 50,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[ImportBatchSummary]:
    """
    Return the most recent CSV import batch records (admin only).
    """
    result = await db.execute(
        select(ImportBatch)
        .order_by(desc(ImportBatch.created_at))
        .limit(min(limit, 200))
    )
    batches = result.scalars().all()

    return [
        ImportBatchSummary(
            id=b.id,
            original_filename=b.original_filename,
            uploaded_by_username=b.uploaded_by_username,
            uploaded_by_display_name=b.uploaded_by_display_name,
            original_rows=b.original_rows,
            valid_rows=b.valid_rows,
            imported_rows=b.imported_rows,
            duplicate_rows=b.duplicate_rows,
            invalid_rows=b.invalid_rows,
            scored=b.scored,
            approve_count=b.approve_count,
            review_count=b.review_count,
            block_count=b.block_count,
            mode=b.mode,
            status=b.status,
            processing_time_ms=b.processing_time_ms,
            created_at=b.created_at,
            completed_at=b.completed_at,
        )
        for b in batches
    ]


# ---------------------------------------------------------------------------
# DELETE /api/data-import/{batch_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{batch_id}",
    summary="Delete an import batch and all its transactions",
)
async def delete_import_batch(
    batch_id: int,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Delete all transactions belonging to batch_id, then delete the batch record.
    Requires admin role. This is irreversible.
    """
    # Verify batch exists
    result = await db.execute(select(ImportBatch).where(ImportBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import batch #{batch_id} not found.",
        )

    filename = batch.original_filename
    imported_rows = batch.imported_rows or 0

    # Delete all transactions that belong to this batch
    # ShapExplanations are cascade-deleted via the ORM relationship
    del_result = await db.execute(
        delete(Transaction).where(Transaction.import_batch_id == batch_id)
    )
    deleted_tx = del_result.rowcount

    # Delete the batch record itself
    await db.delete(batch)

    await _log_import_event(
        db, "DATA_IMPORT_DELETED", current_user,
        f"Import batch #{batch_id} deleted: '{filename}' ({deleted_tx} transactions removed)",
        {"batch_id": batch_id, "filename": filename, "deleted_transactions": deleted_tx},
        log_level="WARNING",
    )
    await db.commit()

    logger.info(
        "Batch #%d deleted by %s: %d transactions removed ('%s')",
        batch_id, current_user.username, deleted_tx, filename,
    )
    return {
        "deleted": True,
        "batch_id": batch_id,
        "filename": filename,
        "transactions_deleted": deleted_tx,
    }


# ---------------------------------------------------------------------------
# GET /api/data-import/{batch_id}/transactions
# ---------------------------------------------------------------------------

@router.get(
    "/{batch_id}/transactions",
    summary="List transactions belonging to a specific import batch",
)
async def get_batch_transactions(
    batch_id: int,
    page: int = 1,
    page_size: int = 20,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Paginated list of transactions from a specific import batch.
    Returns compact transaction records suitable for the batch detail view.
    """
    # Verify batch exists
    result = await db.execute(select(ImportBatch).where(ImportBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import batch #{batch_id} not found.",
        )

    page_size = min(max(1, page_size), 100)
    offset = (max(1, page) - 1) * page_size

    count_result = await db.execute(
        select(Transaction.id).where(Transaction.import_batch_id == batch_id)
    )
    total = len(count_result.scalars().all())

    items_result = await db.execute(
        select(Transaction)
        .where(Transaction.import_batch_id == batch_id)
        .order_by(Transaction.id.asc())
        .offset(offset)
        .limit(page_size)
    )
    txs = items_result.scalars().all()

    return {
        "batch_id": batch_id,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "items": [
            {
                "id": tx.id,
                "transaction_uuid": tx.transaction_uuid,
                "synthetic_user_id": tx.synthetic_user_id,
                "amount": tx.amount,
                "final_score": tx.final_score,
                "xgb_score": tx.xgb_score,
                "if_score": tx.if_score,
                "decision_tier": tx.decision_tier,
                "true_label": tx.true_label,
                "created_at": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx in txs
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/data-import/{batch_id}/rescore
# ---------------------------------------------------------------------------

@router.post(
    "/{batch_id}/rescore",
    summary="Re-run fraud scoring on all transactions in a batch",
)
async def rescore_batch(
    batch_id: int,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Re-run the fraud scoring service on all stored feature vectors in the batch.
    Updates xgb_score, if_score, final_score, and decision_tier in-place.
    Uses current live thresholds — no re-preprocessing needed.
    Requires admin role.
    """
    import numpy as np
    from sqlalchemy import update as sql_update
    from app.core.config import settings
    from app.models.orm import ThresholdConfig

    # Verify batch exists
    result = await db.execute(select(ImportBatch).where(ImportBatch.id == batch_id))
    batch = result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Import batch #{batch_id} not found.",
        )

    # Load scoring service
    try:
        scoring_svc = get_scoring_service()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Scoring service unavailable: {exc}",
        )

    # Get current live thresholds
    thresh_result = await db.execute(
        select(ThresholdConfig).order_by(ThresholdConfig.id.desc()).limit(1)
    )
    tc = thresh_result.scalar_one_or_none()
    block_threshold  = tc.block_threshold  if tc else settings.DEFAULT_BLOCK_THRESHOLD
    review_threshold = tc.review_threshold if tc else settings.DEFAULT_REVIEW_THRESHOLD

    # Load all transactions for this batch
    txs_result = await db.execute(
        select(Transaction).where(Transaction.import_batch_id == batch_id)
    )
    txs = txs_result.scalars().all()

    if not txs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transactions found for batch #{batch_id}.",
        )

    t_start = __import__("time").time()
    approve_count = review_count = block_count = 0

    for tx in txs:
        # Rebuild feature vector from stored v_features + behavioral features
        v_list = [float(tx.v_features.get(f"V{i}", 0.0)) for i in range(1, 29)]
        behavioral = {
            "tx_freq_1h":         tx.tx_freq_1h or 0.0,
            "tx_freq_24h":        tx.tx_freq_24h or 0.0,
            "amount_deviation_z": tx.amount_deviation_z or 0.0,
            "time_of_day_risk":   tx.time_of_day_risk or 0,
            "velocity_change":    tx.velocity_change or 0.0,
            "location_entropy":   tx.location_entropy or 0,
        }

        score_result = scoring_svc.score_transaction(
            v_features=v_list,
            amount=tx.amount,
            time_val=tx.time_val,
            behavioral_features=behavioral,
            block_threshold=block_threshold,
            review_threshold=review_threshold,
        )

        tx.xgb_score     = score_result["xgb_score"]
        tx.if_score      = score_result["if_score"]
        tx.final_score   = score_result["final_score"]
        tx.decision_tier = score_result["decision_tier"]

        if tx.decision_tier == "APPROVE":
            approve_count += 1
        elif tx.decision_tier == "REVIEW":
            review_count += 1
        else:
            block_count += 1

    # Update batch scoring summary
    batch.scored        = True
    batch.approve_count = approve_count
    batch.review_count  = review_count
    batch.block_count   = block_count

    await _log_import_event(
        db, "DATA_IMPORT_RESCORED", current_user,
        f"Batch #{batch_id} rescored: {len(txs)} transactions re-evaluated",
        {"batch_id": batch_id, "rows": len(txs), "approve": approve_count,
         "review": review_count, "block": block_count},
    )
    await db.commit()

    t_ms = int((__import__("time").time() - t_start) * 1000)
    return {
        "rescored": True,
        "batch_id": batch_id,
        "rows_rescored": len(txs),
        "approve_count": approve_count,
        "review_count": review_count,
        "block_count": block_count,
        "processing_time_ms": t_ms,
    }


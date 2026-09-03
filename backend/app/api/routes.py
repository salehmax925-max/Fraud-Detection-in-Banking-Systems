"""
backend/app/api/routes.py
==========================
All FastAPI API routers — mounted in main.py

Endpoints:
  POST /api/score
  GET  /api/transactions
  GET  /api/transactions/{id}
  GET  /api/review-queue
  POST /api/review-queue/{id}/decision
  GET  /api/digital-twin/{user_id}
  GET  /api/admin/thresholds
  PUT  /api/admin/thresholds
  GET  /api/metrics
  GET  /api/simulate
"""
from __future__ import annotations

import logging
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.digital_twin import DigitalTwinEngine, get_digital_twin_engine
from app.models.orm import (
    DigitalTwinProfile,
    ReviewQueue,
    ShapExplanation,
    ThresholdConfig,
    Transaction,
    User,
)
from app.models.auth import ThresholdAudit
from app.schemas.schemas import (
    DigitalTwinSummary,
    AmountStats,
    MetricsResponse,
    PaginatedTransactions,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueItem,
    ScoreRequest,
    ScoreResponse,
    ShapFeature,
    SimulationResponse,
    ThresholdRead,
    ThresholdUpdate,
    TransactionDetail,
    TransactionListItem,
)
from app.services.scoring import ScoringService, get_scoring_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def get_current_thresholds(db: AsyncSession) -> tuple[float, float]:
    """Get the current block/review thresholds from DB (or defaults)."""
    result = await db.execute(select(ThresholdConfig).order_by(ThresholdConfig.id.desc()).limit(1))
    tc = result.scalar_one_or_none()
    if tc:
        return tc.block_threshold, tc.review_threshold
    return settings.DEFAULT_BLOCK_THRESHOLD, settings.DEFAULT_REVIEW_THRESHOLD


def _transaction_to_list_item(tx: Transaction) -> TransactionListItem:
    return TransactionListItem(
        id=tx.id,
        transaction_uuid=tx.transaction_uuid,
        synthetic_user_id=tx.synthetic_user_id,
        amount=tx.amount,
        time_val=tx.time_val,
        final_score=tx.final_score,
        xgb_score=tx.xgb_score,
        if_score=tx.if_score,
        decision_tier=tx.decision_tier,
        is_simulation=tx.is_simulation,
        true_label=tx.true_label,
        import_batch_id=tx.import_batch_id,
        created_at=tx.created_at,
    )


def _shap_orm_to_schema(shap_orm: ShapExplanation) -> ShapFeature:
    return ShapFeature(
        feature_name=shap_orm.feature_name,
        shap_value=shap_orm.shap_value,
        feature_value=shap_orm.feature_value,
        direction=shap_orm.direction,
        rank=shap_orm.rank,
    )


# ---------------------------------------------------------------------------
# POST /api/score
# ---------------------------------------------------------------------------

@router.post("/score", response_model=ScoreResponse, tags=["Scoring"])
async def score_transaction(
    request: ScoreRequest,
    db: AsyncSession = Depends(get_db),
    scoring: ScoringService = Depends(get_scoring_service),
    dt_engine: DigitalTwinEngine = Depends(get_digital_twin_engine),
) -> ScoreResponse:
    """
    Score a transaction through the full fraud detection pipeline:
    1. Digital Twin Engine computes behavioral features
    2. XGBoost + Isolation Forest scoring
    3. Score fusion (0.70 XGB + 0.30 IF)
    4. Tiered decision (0.85/0.50)
    5. SHAP explanation (if score >= 0.50)
    6. Persist to PostgreSQL
    """
    # Generate synthetic user ID if not provided
    if request.synthetic_user_id:
        synthetic_user_id = request.synthetic_user_id
    else:
        from ml.preprocessing import generate_synthetic_user_id
        synthetic_user_id = generate_synthetic_user_id(request.time_val, request.amount)

    # Get live thresholds from DB
    block_threshold, review_threshold = await get_current_thresholds(db)

    # Step 1: Compute behavioral features via Digital Twin Engine
    tx_meta = {"amount": request.amount, "time_val": request.time_val}
    behavioral_features = await dt_engine.compute_features_and_update(
        user_id=synthetic_user_id,
        timestamp=request.time_val,
        amount=request.amount,
        device_marker=request.device_marker,
        tx_metadata=tx_meta,
        db_session=db,
    )

    # Step 2-4: Score through fusion pipeline
    v_features = request.get_v_features_list()
    score_result = scoring.score_transaction(
        v_features=v_features,
        amount=request.amount,
        time_val=request.time_val,
        behavioral_features=behavioral_features,
        block_threshold=block_threshold,
        review_threshold=review_threshold,
    )

    xgb_score = score_result["xgb_score"]
    if_score = score_result["if_score"]
    final_score = score_result["final_score"]
    decision_tier = score_result["decision_tier"]
    feature_vector = score_result["feature_vector"]

    # Update Digital Twin with the risk score for EMA trend
    await dt_engine.compute_features_and_update(
        user_id=synthetic_user_id,
        timestamp=request.time_val + 0.001,  # tiny offset to avoid duplicate
        amount=request.amount,
        risk_score=final_score,
        db_session=None,  # skip DB persistence for this tiny update
    )

    # Step 5: SHAP explanation — computed for ALL transactions (no threshold gate)
    shap_features_orm = []
    shap_features_schema = []
    fv_array = np.array(feature_vector, dtype=np.float64)
    raw_shap = scoring.get_shap_explanation(fv_array, top_n=10)
    for item in raw_shap:
        shap_features_schema.append(ShapFeature(**item))
        shap_features_orm.append(item)

    # Step 6: Persist to PostgreSQL
    # Get or create User
    user_result = await db.execute(select(User).where(User.synthetic_user_id == synthetic_user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        user = User(synthetic_user_id=synthetic_user_id)
        db.add(user)
        await db.flush()

    # Create Transaction record
    tx = Transaction(
        transaction_uuid=str(uuid_lib.uuid4()),
        user_id=user.id,
        synthetic_user_id=synthetic_user_id,
        time_val=request.time_val,
        amount=request.amount,
        v_features=request.get_v_features_dict(),
        tx_freq_1h=behavioral_features.get("tx_freq_1h"),
        tx_freq_24h=behavioral_features.get("tx_freq_24h"),
        amount_deviation_z=behavioral_features.get("amount_deviation_z"),
        time_of_day_risk=behavioral_features.get("time_of_day_risk"),
        velocity_change=behavioral_features.get("velocity_change"),
        location_entropy=behavioral_features.get("location_entropy"),
        xgb_score=xgb_score,
        if_score=if_score,
        final_score=final_score,
        decision_tier=decision_tier,
        is_simulation=False,
        true_label=request.true_label,
        created_at=datetime.now(timezone.utc),
    )
    db.add(tx)
    await db.flush()  # get tx.id

    # Save SHAP explanations
    for item in shap_features_orm:
        shap_orm = ShapExplanation(
            transaction_id=tx.id,
            feature_name=item["feature_name"],
            shap_value=item["shap_value"],
            feature_value=item["feature_value"],
            direction=item["direction"],
            rank=item["rank"],
        )
        db.add(shap_orm)

    # Add to review queue if REVIEW tier
    if decision_tier == "REVIEW":
        rq = ReviewQueue(transaction_id=tx.id, status="pending")
        db.add(rq)

    await db.flush()

    return ScoreResponse(
        transaction_id=tx.id,
        transaction_uuid=tx.transaction_uuid,
        synthetic_user_id=synthetic_user_id,
        xgb_score=xgb_score,
        if_score=if_score,
        final_score=final_score,
        decision_tier=decision_tier,
        behavioral_features=behavioral_features,
        shap_explanations=shap_features_schema if shap_features_schema else None,
        is_simulation=False,
        true_label=request.true_label,
        created_at=tx.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/transactions
# ---------------------------------------------------------------------------

@router.get("/transactions", response_model=PaginatedTransactions, tags=["Transactions"])
async def list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    decision_tier: Optional[str] = Query(None, description="Filter: BLOCK | REVIEW | APPROVE"),
    user_id: Optional[str] = Query(None, description="Filter by synthetic_user_id"),
    import_batch_id: Optional[int] = Query(None, description="Filter by CSV import batch ID"),
    source: Optional[str] = Query(None, description="Filter source: simulation | live | imported"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedTransactions:
    """
    Paginated, filterable list of scored transactions.
    Supports filtering by tier, user, import batch, and source type.
    """
    conditions = []
    if decision_tier:
        tier_upper = decision_tier.upper()
        if tier_upper not in ("BLOCK", "REVIEW", "APPROVE"):
            raise HTTPException(status_code=400, detail="decision_tier must be BLOCK, REVIEW, or APPROVE")
        conditions.append(Transaction.decision_tier == tier_upper)
    if user_id:
        conditions.append(Transaction.synthetic_user_id == user_id)
    if import_batch_id is not None:
        conditions.append(Transaction.import_batch_id == import_batch_id)
    if source:
        if source == "simulation":
            conditions.append(Transaction.is_simulation == True)
        elif source == "live":
            conditions.append(Transaction.is_simulation == False)
            conditions.append(Transaction.import_batch_id.is_(None))
        elif source == "imported":
            conditions.append(Transaction.import_batch_id.isnot(None))

    base_query = select(Transaction)
    if conditions:
        base_query = base_query.where(and_(*conditions))

    # Count total
    count_q = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    items_result = await db.execute(
        base_query.order_by(Transaction.created_at.desc()).offset(offset).limit(page_size)
    )
    transactions = items_result.scalars().all()

    return PaginatedTransactions(
        items=[_transaction_to_list_item(tx) for tx in transactions],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


# ---------------------------------------------------------------------------
# GET /api/transactions/{id}
# ---------------------------------------------------------------------------

@router.get("/transactions/{transaction_id}", response_model=TransactionDetail, tags=["Transactions"])
async def get_transaction(
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
) -> TransactionDetail:
    """Full transaction detail including all features and SHAP breakdown."""
    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.shap_explanations), selectinload(Transaction.review_queue_entry))
        .where(Transaction.id == transaction_id)
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

    review_status = None
    if tx.review_queue_entry:
        review_status = tx.review_queue_entry.status

    return TransactionDetail(
        id=tx.id,
        transaction_uuid=tx.transaction_uuid,
        synthetic_user_id=tx.synthetic_user_id,
        amount=tx.amount,
        time_val=tx.time_val,
        final_score=tx.final_score,
        xgb_score=tx.xgb_score,
        if_score=tx.if_score,
        decision_tier=tx.decision_tier,
        is_simulation=tx.is_simulation,
        created_at=tx.created_at,
        v_features=tx.v_features or {},
        tx_freq_1h=tx.tx_freq_1h,
        tx_freq_24h=tx.tx_freq_24h,
        amount_deviation_z=tx.amount_deviation_z,
        time_of_day_risk=tx.time_of_day_risk,
        velocity_change=tx.velocity_change,
        location_entropy=tx.location_entropy,
        shap_explanations=[_shap_orm_to_schema(s) for s in sorted(tx.shap_explanations, key=lambda x: x.rank)],
        review_status=review_status,
    )


# ---------------------------------------------------------------------------
# GET /api/review-queue
# ---------------------------------------------------------------------------

@router.get("/review-queue", response_model=list[ReviewQueueItem], tags=["Review Queue"])
async def get_review_queue(
    status: str = Query("pending", description="pending | approved | rejected | all"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewQueueItem]:
    """Get analyst review queue with SHAP explanations."""
    query = (
        select(ReviewQueue)
        .options(
            selectinload(ReviewQueue.transaction).selectinload(Transaction.shap_explanations)
        )
        .order_by(ReviewQueue.created_at.desc())
        .limit(limit)
    )
    if status != "all":
        query = query.where(ReviewQueue.status == status)

    result = await db.execute(query)
    queue_items = result.scalars().all()

    items = []
    for rq in queue_items:
        tx = rq.transaction
        if tx is None:
            continue
        items.append(ReviewQueueItem(
            id=rq.id,
            transaction_id=tx.id,
            transaction_uuid=tx.transaction_uuid,
            synthetic_user_id=tx.synthetic_user_id,
            amount=tx.amount,
            final_score=tx.final_score or 0.0,
            xgb_score=tx.xgb_score or 0.0,
            if_score=tx.if_score or 0.0,
            status=rq.status,
            analyst_note=rq.analyst_note,
            reviewed_at=rq.reviewed_at,
            created_at=rq.created_at,
            shap_explanations=[_shap_orm_to_schema(s) for s in sorted(tx.shap_explanations, key=lambda x: x.rank)],
        ))
    return items


# ---------------------------------------------------------------------------
# POST /api/review-queue/{id}/decision
# ---------------------------------------------------------------------------

@router.post("/review-queue/{queue_id}/decision", response_model=ReviewDecisionResponse, tags=["Review Queue"])
async def submit_review_decision(
    queue_id: int,
    body: ReviewDecisionRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewDecisionResponse:
    """Analyst approves or rejects a review-tier transaction."""
    result = await db.execute(select(ReviewQueue).where(ReviewQueue.id == queue_id))
    rq = result.scalar_one_or_none()
    if rq is None:
        raise HTTPException(status_code=404, detail=f"Review queue item {queue_id} not found")
    if rq.status != "pending":
        raise HTTPException(status_code=400, detail=f"Item already reviewed with status '{rq.status}'")

    rq.status = body.decision  # "approved" or "rejected"
    rq.analyst_note = body.analyst_note
    rq.reviewed_at = datetime.now(timezone.utc)
    await db.flush()

    return ReviewDecisionResponse(
        id=rq.id,
        transaction_id=rq.transaction_id,
        status=rq.status,
        analyst_note=rq.analyst_note,
        reviewed_at=rq.reviewed_at,
    )


# ---------------------------------------------------------------------------
# GET /api/digital-twin/{user_id}
# ---------------------------------------------------------------------------

@router.get("/digital-twin/{user_id}", response_model=DigitalTwinSummary, tags=["Digital Twin"])
async def get_digital_twin(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    dt_engine: DigitalTwinEngine = Depends(get_digital_twin_engine),
) -> DigitalTwinSummary:
    """
    Get the current Digital Twin behavioral profile for a user.
    Shows rolling behavioral stats: frequency, amounts, devices, risk trend.
    """
    summary = await dt_engine.get_profile_summary(user_id, db_session=db)
    if summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"No transaction history found for user '{user_id}'. "
                   "Score at least one transaction for this user first."
        )

    return DigitalTwinSummary(
        user_id=summary["user_id"],
        total_transactions=summary["total_transactions"],
        amount_stats=AmountStats(**summary["amount_stats"]),
        known_devices=summary["known_devices"],
        known_device_count=summary["known_device_count"],
        recent_transactions=summary.get("recent_transactions", []),
        current_risk_trend=summary.get("current_risk_trend"),
        last_24h_tx_count=summary.get("last_24h_tx_count", 0),
        updated_at=datetime.fromisoformat(summary["updated_at"]) if summary.get("updated_at") else None,
    )


# ---------------------------------------------------------------------------
# GET /api/admin/thresholds
# ---------------------------------------------------------------------------

@router.get("/admin/thresholds", response_model=ThresholdRead, tags=["Admin"])
async def get_thresholds(db: AsyncSession = Depends(get_db)) -> ThresholdRead:
    """Get current block/review thresholds with audit trail info."""
    result = await db.execute(select(ThresholdConfig).order_by(ThresholdConfig.id.desc()).limit(1))
    tc = result.scalar_one_or_none()
    if tc is None:
        # Return defaults (no record in DB yet)
        return ThresholdRead(
            id=0,
            block_threshold=settings.DEFAULT_BLOCK_THRESHOLD,
            review_threshold=settings.DEFAULT_REVIEW_THRESHOLD,
            updated_at=datetime.now(timezone.utc),
            updated_by=None,
        )
    # Also fetch the latest audit entry for display name
    audit_result = await db.execute(
        select(ThresholdAudit).order_by(ThresholdAudit.updated_at.desc()).limit(1)
    )
    latest_audit = audit_result.scalar_one_or_none()
    return ThresholdRead(
        id=tc.id,
        block_threshold=tc.block_threshold,
        review_threshold=tc.review_threshold,
        updated_at=tc.updated_at,
        updated_by=tc.updated_by,
        last_updated_display_name=latest_audit.updated_by_display_name if latest_audit else None,
        last_updated_at=latest_audit.updated_at if latest_audit else None,
    )


# ---------------------------------------------------------------------------
# PUT /api/admin/thresholds
# ---------------------------------------------------------------------------

@router.put("/admin/thresholds", response_model=ThresholdRead, tags=["Admin"])
async def update_thresholds(
    body: ThresholdUpdate,
    db: AsyncSession = Depends(get_db),
    scoring: ScoringService = Depends(get_scoring_service),
) -> ThresholdRead:
    """
    Update block/review thresholds live — takes effect IMMEDIATELY without retraining.
    Validates: block_threshold > review_threshold.
    Logs to threshold_audit table for audit trail.
    """
    if body.block_threshold <= body.review_threshold:
        raise HTTPException(
            status_code=400,
            detail=f"block_threshold ({body.block_threshold}) must be greater than review_threshold ({body.review_threshold})"
        )

    # Get previous thresholds for audit trail
    prev_block, prev_review = await get_current_thresholds(db)

    # Create new threshold record
    tc = ThresholdConfig(
        block_threshold=body.block_threshold,
        review_threshold=body.review_threshold,
        updated_by=body.updated_by,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(tc)
    await db.flush()

    # Log to threshold_audit for audit trail (who changed what, when)
    if body.updated_by:
        # Parse display name from updated_by (format: "username|DisplayName" or just username)
        parts = (body.updated_by or "").split("|", 1)
        uname = parts[0].strip()
        dname = parts[1].strip() if len(parts) > 1 else uname
        audit_entry = ThresholdAudit(
            updated_by_username=uname,
            updated_by_display_name=dname,
            previous_threshold_block=prev_block,
            previous_threshold_review=prev_review,
            new_threshold_block=body.block_threshold,
            new_threshold_review=body.review_threshold,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(audit_entry)
        await db.flush()

    # Update scoring service in memory (takes effect immediately)
    scoring.update_thresholds(body.block_threshold, body.review_threshold)
    logger.info(
        "Thresholds updated live: block=%.2f, review=%.2f (by %s)",
        body.block_threshold, body.review_threshold, body.updated_by or "unknown",
    )

    return ThresholdRead(
        id=tc.id,
        block_threshold=tc.block_threshold,
        review_threshold=tc.review_threshold,
        updated_at=tc.updated_at,
        updated_by=tc.updated_by,
    )


# ---------------------------------------------------------------------------
# GET /api/metrics
# ---------------------------------------------------------------------------

@router.get("/metrics", response_model=MetricsResponse, tags=["Model Performance"])
async def get_metrics(
    scoring: ScoringService = Depends(get_scoring_service),
) -> MetricsResponse:
    """
    Return model evaluation metrics from evaluation_report.json.
    Every number comes from the real test-set evaluation — never hardcoded.
    """
    report = scoring.evaluation_report
    if not report:
        raise HTTPException(
            status_code=503,
            detail="Model evaluation report not available. Ensure models/ contains evaluation_report.json."
        )
    return MetricsResponse(**report)


# ---------------------------------------------------------------------------
# GET /api/simulate
# ---------------------------------------------------------------------------

@router.get("/simulate", response_model=SimulationResponse, tags=["Simulation"])
async def simulate_transactions(
    batch_size: int = Query(20, ge=1, le=100, description="Number of test-set rows to replay"),
    seed: Optional[int] = Query(None, description="Random seed for deterministic demo mode (e.g. 42)"),
    realistic: bool = Query(False, description="If True, sample proportional to real dataset fraud rate (~0.17%). If False (default), inject 35% fraud for demo showcase."),
    db: AsyncSession = Depends(get_db),
    scoring: ScoringService = Depends(get_scoring_service),
    dt_engine: DigitalTwinEngine = Depends(get_digital_twin_engine),
) -> SimulationResponse:
    """
    Replay real rows from the held-out test split through the scoring pipeline.

    DISCLAIMER: These are real ULB dataset rows from the test split.
    They are NOT live bank traffic. Clearly labeled as simulation in all UI.
    """
    import pandas as pd
    from pathlib import Path

    # Load test split
    test_parquet = settings.processed_dir_path / "test.parquet"
    if not test_parquet.exists():
        raise HTTPException(
            status_code=503,
            detail="Test split not found. Run: python scripts/run_preprocessing.py"
        )

    test_df = pd.read_parquet(test_parquet, engine="pyarrow")

    # Split into fraud and legit sub-frames for controlled sampling
    fraud_df = test_df[test_df["Class"] == 1]
    legit_df = test_df[test_df["Class"] == 0]

    # Sample batch_size rows.
    # Demo mode (default): 35% fraud for better REVIEW-tier coverage in showcases.
    # Realistic mode (realistic=True): ~0.17% fraud matching real ULB dataset distribution.
    # Use seed for deterministic replay (e.g. seed=42 guarantees consistent results).
    rng_state = seed  # None = random each call, int = deterministic demo mode

    if realistic:
        # Real dataset distribution: 0.17% fraud — use proportional sampling
        n_fraud = min(max(0, round(batch_size * 0.0017)), len(fraud_df))
        n_legit = min(batch_size - n_fraud, len(legit_df))
        logger.info("Simulation: realistic mode — %d fraud, %d legit out of %d", n_fraud, n_legit, batch_size)
    else:
        # Demo mode: inflate fraud to 35% for showcase visibility
        n_fraud = min(max(2, int(batch_size * 0.35)), len(fraud_df))
        n_legit = min(batch_size - n_fraud, len(legit_df))
        logger.info("Simulation: demo mode (35%% fraud injection) — %d fraud, %d legit out of %d", n_fraud, n_legit, batch_size)

    sample_fraud = fraud_df.sample(n=n_fraud, random_state=rng_state) if n_fraud > 0 else fraud_df.iloc[0:0]
    sample_legit = legit_df.sample(n=n_legit, random_state=rng_state)
    sample_df = pd.concat([sample_fraud, sample_legit]).sample(frac=1, random_state=rng_state)

    scored_transactions = []
    block_threshold, review_threshold = await get_current_thresholds(db)

    for _, row in sample_df.iterrows():
        from ml.preprocessing import generate_synthetic_user_id
        synthetic_user_id = generate_synthetic_user_id(float(row["Time"]), float(row["Amount"]))
        v_features = [float(row.get(f"V{i}", 0.0)) for i in range(1, 29)]

        # Behavioral features
        behavioral_features = await dt_engine.compute_features_and_update(
            user_id=synthetic_user_id,
            timestamp=float(row["Time"]),
            amount=float(row["Amount"]),
            db_session=db,
        )

        # Score
        score_result = scoring.score_transaction(
            v_features=v_features,
            amount=float(row["Amount"]),
            time_val=float(row["Time"]),
            behavioral_features=behavioral_features,
            block_threshold=block_threshold,
            review_threshold=review_threshold,
        )

        xgb_score = score_result["xgb_score"]
        if_score = score_result["if_score"]
        final_score = score_result["final_score"]
        decision_tier = score_result["decision_tier"]
        feature_vector = score_result["feature_vector"]

        # SHAP for all tiers (no threshold gate)
        fv_array = np.array(feature_vector, dtype=np.float64)
        raw_shap = scoring.get_shap_explanation(fv_array, top_n=10)
        shap_features = [ShapFeature(**s) for s in raw_shap]

        # Persist to DB
        user_result = await db.execute(select(User).where(User.synthetic_user_id == synthetic_user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            user = User(synthetic_user_id=synthetic_user_id)
            db.add(user)
            await db.flush()

        v_dict = {f"V{i}": float(row.get(f"V{i}", 0.0)) for i in range(1, 29)}
        true_label_val = int(row["Class"]) if "Class" in row.index else None
        tx = Transaction(
            transaction_uuid=str(uuid_lib.uuid4()),
            user_id=user.id,
            synthetic_user_id=synthetic_user_id,
            time_val=float(row["Time"]),
            amount=float(row["Amount"]),
            v_features=v_dict,
            tx_freq_1h=behavioral_features.get("tx_freq_1h"),
            tx_freq_24h=behavioral_features.get("tx_freq_24h"),
            amount_deviation_z=behavioral_features.get("amount_deviation_z"),
            time_of_day_risk=behavioral_features.get("time_of_day_risk"),
            velocity_change=behavioral_features.get("velocity_change"),
            location_entropy=behavioral_features.get("location_entropy"),
            xgb_score=xgb_score,
            if_score=if_score,
            final_score=final_score,
            decision_tier=decision_tier,
            is_simulation=True,
            true_label=true_label_val,
            created_at=datetime.now(timezone.utc),
        )
        db.add(tx)
        await db.flush()

        for item in [s.model_dump() for s in shap_features]:
            db.add(ShapExplanation(
                transaction_id=tx.id,
                feature_name=item["feature_name"],
                shap_value=item["shap_value"],
                feature_value=item["feature_value"],
                direction=item["direction"],
                rank=item["rank"],
            ))

        if decision_tier == "REVIEW":
            db.add(ReviewQueue(transaction_id=tx.id, status="pending"))

        await db.flush()

        scored_transactions.append(ScoreResponse(
            transaction_id=tx.id,
            transaction_uuid=tx.transaction_uuid,
            synthetic_user_id=synthetic_user_id,
            xgb_score=xgb_score,
            if_score=if_score,
            final_score=final_score,
            decision_tier=decision_tier,
            behavioral_features=behavioral_features,
            shap_explanations=shap_features if shap_features else None,
            is_simulation=True,
            true_label=int(row["Class"]) if "Class" in row.index else None,
            created_at=tx.created_at,
        ))

    return SimulationResponse(
        scored_count=len(scored_transactions),
        transactions=scored_transactions,
    )


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------

@router.get("/stats", tags=["Dashboard"])
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """True DB-level counts per decision tier and pending review queue — used by the Live Dashboard."""
    # Only count transactions that have actually been scored (decision_tier IS NOT NULL)
    scored_r  = await db.execute(select(func.count(Transaction.id)).where(Transaction.decision_tier.isnot(None)))
    block_r   = await db.execute(select(func.count(Transaction.id)).where(Transaction.decision_tier == "BLOCK"))
    review_r  = await db.execute(select(func.count(Transaction.id)).where(Transaction.decision_tier == "REVIEW"))
    approve_r = await db.execute(select(func.count(Transaction.id)).where(Transaction.decision_tier == "APPROVE"))
    pending_r = await db.execute(select(func.count(ReviewQueue.id)).where(ReviewQueue.status == "pending"))

    return {
        "total": scored_r.scalar() or 0,
        "block": block_r.scalar() or 0,
        "review": review_r.scalar() or 0,
        "approve": approve_r.scalar() or 0,
        "pending_review": pending_r.scalar() or 0,
    }


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------

@router.get("/users", tags=["Users"])
async def list_users_with_profiles(
    limit: int = Query(2000, ge=1, le=5000),
    q: Optional[str] = Query(None, description="Filter by user ID string"),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all users that have at least one transaction — used by the Digital Twin dropdown."""
    query = (
        select(
            User.synthetic_user_id,
            func.count(Transaction.id).label("transaction_count"),
        )
        .outerjoin(Transaction, Transaction.user_id == User.id)
        .group_by(User.synthetic_user_id)
    )
    if isinstance(q, str) and q.strip():
        query = query.where(User.synthetic_user_id.ilike(f"%{q.strip()}%"))
    query = query.order_by(func.count(Transaction.id).desc(), User.synthetic_user_id.asc()).limit(limit)

    result = await db.execute(query)
    rows = result.all()
    return [
        {"user_id": row.synthetic_user_id, "transaction_count": row.transaction_count}
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@router.get("/health", tags=["Health"])
async def health_check() -> dict:
    return {
        "status": "healthy",
        "service": "Fraud Detection API",
        "version": "1.0.0",
    }

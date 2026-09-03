// src/types/index.ts
// TypeScript types matching the FastAPI Pydantic schemas exactly

export interface ShapFeature {
  feature_name: string
  shap_value: number
  feature_value: number
  direction: 'increases_risk' | 'decreases_risk'
  rank: number
}

export interface ScoreRequest {
  time_val: number
  amount: number
  v1?: number; v2?: number; v3?: number; v4?: number
  v5?: number; v6?: number; v7?: number; v8?: number
  v9?: number; v10?: number; v11?: number; v12?: number
  v13?: number; v14?: number; v15?: number; v16?: number
  v17?: number; v18?: number; v19?: number; v20?: number
  v21?: number; v22?: number; v23?: number; v24?: number
  v25?: number; v26?: number; v27?: number; v28?: number
  synthetic_user_id?: string
  device_marker?: string
  true_label?: number
}

export interface ScoreResponse {
  transaction_id: number
  transaction_uuid: string
  synthetic_user_id: string
  xgb_score: number
  if_score: number
  final_score: number
  decision_tier: 'BLOCK' | 'REVIEW' | 'APPROVE'
  behavioral_features: Record<string, number>
  shap_explanations?: ShapFeature[]
  is_simulation: boolean
  true_label?: number
  created_at: string
}

export interface TransactionListItem {
  id: number
  transaction_uuid: string
  synthetic_user_id: string
  amount: number
  time_val: number
  final_score: number | null
  xgb_score: number | null
  if_score: number | null
  decision_tier: string | null
  is_simulation: boolean
  true_label: number | null   // 0=legitimate, 1=fraud (from ULB dataset; simulation rows only)
  import_batch_id: number | null  // set for CSV-imported rows; null for live/simulation
  created_at: string
}

export interface TransactionDetail extends TransactionListItem {
  v_features: Record<string, number>
  tx_freq_1h: number | null
  tx_freq_24h: number | null
  amount_deviation_z: number | null
  time_of_day_risk: number | null
  velocity_change: number | null
  location_entropy: number | null
  shap_explanations: ShapFeature[]
  review_status: string | null
}

export interface PaginatedTransactions {
  items: TransactionListItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface ReviewQueueItem {
  id: number
  transaction_id: number
  transaction_uuid: string
  synthetic_user_id: string
  amount: number
  final_score: number
  xgb_score: number
  if_score: number
  status: 'pending' | 'approved' | 'rejected'
  analyst_note: string | null
  reviewed_at: string | null
  created_at: string
  shap_explanations: ShapFeature[]
}

export interface ReviewDecisionRequest {
  decision: 'approved' | 'rejected'
  analyst_note?: string
}

export interface ReviewDecisionResponse {
  id: number
  transaction_id: number
  status: string
  analyst_note: string | null
  reviewed_at: string
}

export interface AmountStats {
  count: number
  mean: number
  std: number
}

export interface DigitalTwinSummary {
  user_id: string
  total_transactions: number
  amount_stats: AmountStats
  known_devices: string[]
  known_device_count: number
  recent_transactions: Array<Record<string, unknown>>
  current_risk_trend: number | null
  last_24h_tx_count: number
  updated_at: string | null
}

export interface ThresholdRead {
  id: number
  block_threshold: number
  review_threshold: number
  updated_at: string
  updated_by: string | null
  // Audit trail fields from threshold_audit table
  last_updated_display_name?: string | null
  last_updated_at?: string | null
}

export interface ThresholdUpdate {
  block_threshold: number
  review_threshold: number
  updated_by?: string
}

export interface ModelMetrics {
  model: string
  threshold: number
  precision: number
  recall: number
  f1_score: number
  roc_auc: number
  mcc: number
  confusion_matrix: {
    true_negatives: number
    false_positives: number
    false_negatives: number
    true_positives: number
  }
}

export interface MetricsResponse {
  evaluation_version: string
  test_set_size: number
  test_fraud_count: number
  test_fraud_pct: number
  primary_metrics: ModelMetrics
  block_tier_metrics: ModelMetrics
  model_comparison: {
    hybrid_fusion: ModelMetrics
    xgboost_only: ModelMetrics
    isolation_forest_only: ModelMetrics
  }
  roc_curve_data: {
    hybrid: { fpr: number[]; tpr: number[]; auc: number }
    xgb: { fpr: number[]; tpr: number[]; auc: number }
    if: { fpr: number[]; tpr: number[]; auc: number }
  }
  precision_recall_curve_data: {
    precision: number[]
    recall: number[]
  }
  decision_thresholds: {
    block: number
    review: number
  }
}

export interface SimulationResponse {
  message: string
  disclaimer: string
  scored_count: number
  transactions: ScoreResponse[]
}

// UI helpers
export type DecisionTier = 'BLOCK' | 'REVIEW' | 'APPROVE'

export const TIER_COLORS: Record<string, string> = {
  BLOCK: 'tier-badge-block',
  REVIEW: 'tier-badge-review',
  APPROVE: 'tier-badge-approve',
}

export const TIER_SCORE_GRADIENT: Record<string, string> = {
  BLOCK: 'score-gradient-block',
  REVIEW: 'score-gradient-review',
  APPROVE: 'score-gradient-approve',
}

export const TIER_BORDER_COLOR: Record<string, string> = {
  BLOCK: 'border-block/30',
  REVIEW: 'border-review/30',
  APPROVE: 'border-approve/30',
}

// Dashboard stats (from GET /api/stats — true DB-level counts)
export interface DashboardStats {
  total: number
  block: number
  review: number
  approve: number
  pending_review: number
}

// User list item (from GET /api/users — for Digital Twin dropdown)
export interface UserListItem {
  user_id: string
  transaction_count: number
}

// src/lib/mockData.ts
// Realistic demo data shown when the backend is offline.
// All values are plausible ULB-dataset–like numbers.

import type {
  TransactionListItem, DashboardStats, ReviewQueueItem, ShapFeature, MetricsResponse
} from '../types'

const NOW = new Date().toISOString()
const ago = (mins: number) => new Date(Date.now() - mins * 60000).toISOString()

const mockShap = (tier: string): ShapFeature[] => {
  const features = [
    { feature_name: 'V14', shap_value: tier === 'BLOCK' ? 2.31 : tier === 'REVIEW' ? 0.82 : -0.34, feature_value: -4.12, direction: tier === 'BLOCK' || tier === 'REVIEW' ? 'increases_risk' : 'decreases_risk', rank: 1 },
    { feature_name: 'amount_deviation_z', shap_value: tier === 'BLOCK' ? 1.87 : 0.54, feature_value: 3.71, direction: 'increases_risk', rank: 2 },
    { feature_name: 'V4', shap_value: tier === 'BLOCK' ? -1.22 : 0.41, feature_value: 2.14, direction: tier === 'BLOCK' ? 'decreases_risk' : 'increases_risk', rank: 3 },
    { feature_name: 'tx_freq_1h', shap_value: 0.76, feature_value: 4.0, direction: 'increases_risk', rank: 4 },
    { feature_name: 'V17', shap_value: -0.53, feature_value: -3.71, direction: 'decreases_risk', rank: 5 },
    { feature_name: 'velocity_change', shap_value: 0.48, feature_value: 1.2, direction: 'increases_risk', rank: 6 },
    { feature_name: 'V12', shap_value: -0.31, feature_value: 1.09, direction: 'decreases_risk', rank: 7 },
    { feature_name: 'location_entropy', shap_value: 0.29, feature_value: 1.0, direction: 'increases_risk', rank: 8 },
    { feature_name: 'V10', shap_value: -0.18, feature_value: 0.43, direction: 'decreases_risk', rank: 9 },
    { feature_name: 'tx_freq_24h', shap_value: 0.14, feature_value: 7.0, direction: 'increases_risk', rank: 10 },
  ] as ShapFeature[]
  return features
}

export const MOCK_TRANSACTIONS: TransactionListItem[] = [
  { id: 1, transaction_uuid: 'a1b2c3d4-0001', synthetic_user_id: 'user_0042', amount: 892.31, time_val: 172800, final_score: 0.9312, xgb_score: 0.9541, if_score: 0.8731, decision_tier: 'BLOCK', is_simulation: true, true_label: 1, import_batch_id: null, created_at: ago(2) },
  { id: 2, transaction_uuid: 'a1b2c3d4-0002', synthetic_user_id: 'user_0117', amount: 23.50, time_val: 162100, final_score: 0.0721, xgb_score: 0.0651, if_score: 0.0912, decision_tier: 'APPROVE', is_simulation: true, true_label: 0, import_batch_id: null, created_at: ago(4) },
  { id: 3, transaction_uuid: 'a1b2c3d4-0003', synthetic_user_id: 'user_0305', amount: 451.00, time_val: 159700, final_score: 0.6843, xgb_score: 0.7121, if_score: 0.6123, decision_tier: 'REVIEW', is_simulation: true, true_label: 1, import_batch_id: null, created_at: ago(7) },
  { id: 4, transaction_uuid: 'a1b2c3d4-0004', synthetic_user_id: 'user_0042', amount: 12.99, time_val: 155200, final_score: 0.0312, xgb_score: 0.0271, if_score: 0.0421, decision_tier: 'APPROVE', is_simulation: true, true_label: 0, import_batch_id: null, created_at: ago(11) },
  { id: 5, transaction_uuid: 'a1b2c3d4-0005', synthetic_user_id: 'user_0891', amount: 1540.00, time_val: 150100, final_score: 0.8723, xgb_score: 0.9012, if_score: 0.8001, decision_tier: 'BLOCK', is_simulation: true, true_label: 1, import_batch_id: null, created_at: ago(14) },
  { id: 6, transaction_uuid: 'a1b2c3d4-0006', synthetic_user_id: 'user_1203', amount: 67.45, time_val: 144800, final_score: 0.5511, xgb_score: 0.5723, if_score: 0.5082, decision_tier: 'REVIEW', is_simulation: true, true_label: 0, import_batch_id: null, created_at: ago(19) },
  { id: 7, transaction_uuid: 'a1b2c3d4-0007', synthetic_user_id: 'user_0305', amount: 199.00, time_val: 140300, final_score: 0.0891, xgb_score: 0.0812, if_score: 0.1021, decision_tier: 'APPROVE', is_simulation: true, true_label: 0, import_batch_id: null, created_at: ago(23) },
  { id: 8, transaction_uuid: 'a1b2c3d4-0008', synthetic_user_id: 'user_0712', amount: 2200.00, time_val: 137900, final_score: 0.9631, xgb_score: 0.9812, if_score: 0.9171, decision_tier: 'BLOCK', is_simulation: true, true_label: 1, import_batch_id: null, created_at: ago(28) },
  { id: 9, transaction_uuid: 'a1b2c3d4-0009', synthetic_user_id: 'user_0117', amount: 5.00, time_val: 130000, final_score: 0.0219, xgb_score: 0.0181, if_score: 0.0321, decision_tier: 'APPROVE', is_simulation: true, true_label: 0, import_batch_id: null, created_at: ago(35) },
  { id: 10, transaction_uuid: 'a1b2c3d4-0010', synthetic_user_id: 'user_1891', amount: 750.00, time_val: 125500, final_score: 0.7234, xgb_score: 0.7512, if_score: 0.6601, decision_tier: 'REVIEW', is_simulation: true, true_label: 1, import_batch_id: null, created_at: ago(42) },
]

export const MOCK_STATS: DashboardStats = { total: 10, block: 3, review: 3, approve: 4, pending_review: 3 }

export const MOCK_REVIEW_QUEUE: ReviewQueueItem[] = [
  {
    id: 1, transaction_id: 3, transaction_uuid: 'a1b2c3d4-0003',
    synthetic_user_id: 'user_0305', amount: 451.00,
    final_score: 0.6843, xgb_score: 0.7121, if_score: 0.6123,
    status: 'pending', analyst_note: null, reviewed_at: null,
    created_at: ago(7), shap_explanations: mockShap('REVIEW'),
  },
  {
    id: 2, transaction_id: 6, transaction_uuid: 'a1b2c3d4-0006',
    synthetic_user_id: 'user_1203', amount: 67.45,
    final_score: 0.5511, xgb_score: 0.5723, if_score: 0.5082,
    status: 'pending', analyst_note: null, reviewed_at: null,
    created_at: ago(19), shap_explanations: mockShap('REVIEW'),
  },
  {
    id: 3, transaction_id: 10, transaction_uuid: 'a1b2c3d4-0010',
    synthetic_user_id: 'user_1891', amount: 750.00,
    final_score: 0.7234, xgb_score: 0.7512, if_score: 0.6601,
    status: 'pending', analyst_note: null, reviewed_at: null,
    created_at: ago(42), shap_explanations: mockShap('REVIEW'),
  },
]

export const MOCK_METRICS: MetricsResponse = {
  evaluation_version: 'demo-mock-v1',
  test_set_size: 56746,
  test_fraud_count: 95,
  test_fraud_pct: 0.1675,
  primary_metrics: {
    model: 'hybrid_fusion',
    threshold: 0.50,
    precision: 0.9012,
    recall: 0.8632,
    f1_score: 0.8818,
    roc_auc: 0.9742,
    mcc: 0.8701,
    confusion_matrix: { true_negatives: 56571, false_positives: 80, false_negatives: 13, true_positives: 82 },
  },
  block_tier_metrics: {
    model: 'block_tier',
    threshold: 0.85,
    precision: 0.9712,
    recall: 0.7263,
    f1_score: 0.8312,
    roc_auc: 0.9742,
    mcc: 0.8402,
    confusion_matrix: { true_negatives: 56630, false_positives: 21, false_negatives: 26, true_positives: 69 },
  },
  model_comparison: {
    hybrid_fusion: {
      model: 'hybrid_fusion', threshold: 0.50,
      precision: 0.9012, recall: 0.8632, f1_score: 0.8818, roc_auc: 0.9742, mcc: 0.8701,
      confusion_matrix: { true_negatives: 56571, false_positives: 80, false_negatives: 13, true_positives: 82 },
    },
    xgboost_only: {
      model: 'xgboost_only', threshold: 0.50,
      precision: 0.8823, recall: 0.8421, f1_score: 0.8617, roc_auc: 0.9651, mcc: 0.8501,
      confusion_matrix: { true_negatives: 56550, false_positives: 101, false_negatives: 15, true_positives: 80 },
    },
    isolation_forest_only: {
      model: 'isolation_forest_only', threshold: 0.50,
      precision: 0.7123, recall: 0.6842, f1_score: 0.6980, roc_auc: 0.8712, mcc: 0.6891,
      confusion_matrix: { true_negatives: 56312, false_positives: 339, false_negatives: 30, true_positives: 65 },
    },
  },
  roc_curve_data: {
    hybrid: { fpr: [0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0], tpr: [0, 0.55, 0.74, 0.82, 0.87, 0.92, 0.95, 0.97, 0.99, 1.0], auc: 0.9742 },
    xgb:    { fpr: [0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0], tpr: [0, 0.50, 0.71, 0.79, 0.84, 0.89, 0.93, 0.96, 0.98, 1.0], auc: 0.9651 },
    if:     { fpr: [0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0],   tpr: [0, 0.38, 0.52, 0.61, 0.71, 0.78, 0.84, 0.88, 0.93, 1.0], auc: 0.8712 },
  },
  precision_recall_curve_data: {
    precision: [1.0, 0.97, 0.94, 0.91, 0.90, 0.88, 0.85, 0.80, 0.75, 0.70],
    recall:    [0.0, 0.45, 0.62, 0.74, 0.86, 0.90, 0.93, 0.95, 0.97, 1.0],
  },
  decision_thresholds: { block: 0.85, review: 0.50 },
}

export function getShapForTx(id: number): ShapFeature[] {
  const tx = MOCK_TRANSACTIONS.find(t => t.id === id)
  return tx ? mockShap(tx.decision_tier || 'APPROVE') : []
}

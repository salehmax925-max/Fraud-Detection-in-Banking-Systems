// src/lib/api.ts
// Axios-based API client — all calls go to http://localhost:8000/api
import axios from 'axios'
import type {
  ScoreRequest, ScoreResponse, PaginatedTransactions,
  TransactionDetail, ReviewQueueItem, ReviewDecisionRequest,
  ReviewDecisionResponse, DigitalTwinSummary, ThresholdRead,
  ThresholdUpdate, MetricsResponse, SimulationResponse,
  DashboardStats, UserListItem,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

// Request/response logging in dev
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

// ─── Scoring ─────────────────────────────────────────────────────────────────
export const scoreTransaction = async (data: ScoreRequest): Promise<ScoreResponse> => {
  const r = await api.post<ScoreResponse>('/score', data)
  return r.data
}

// ─── Transactions ─────────────────────────────────────────────────────────────
export const getTransactions = async (params: {
  page?: number
  page_size?: number
  decision_tier?: string
  user_id?: string
  import_batch_id?: number
  source?: 'simulation' | 'live' | 'imported'
} = {}): Promise<PaginatedTransactions> => {
  const r = await api.get<PaginatedTransactions>('/transactions', { params })
  return r.data
}

export const getTransaction = async (id: number): Promise<TransactionDetail> => {
  const r = await api.get<TransactionDetail>(`/transactions/${id}`)
  return r.data
}

// ─── Review Queue ─────────────────────────────────────────────────────────────
export const getReviewQueue = async (status = 'pending'): Promise<ReviewQueueItem[]> => {
  const r = await api.get<ReviewQueueItem[]>('/review-queue', { params: { status } })
  return r.data
}

export const submitReviewDecision = async (
  queueId: number,
  data: ReviewDecisionRequest
): Promise<ReviewDecisionResponse> => {
  const r = await api.post<ReviewDecisionResponse>(`/review-queue/${queueId}/decision`, data)
  return r.data
}

// ─── Digital Twin ──────────────────────────────────────────────────────────────
export const getDigitalTwin = async (userId: string): Promise<DigitalTwinSummary> => {
  const r = await api.get<DigitalTwinSummary>(`/digital-twin/${userId}`)
  return r.data
}

// ─── Admin Thresholds ──────────────────────────────────────────────────────────
export const getThresholds = async (): Promise<ThresholdRead> => {
  const r = await api.get<ThresholdRead>('/admin/thresholds')
  return r.data
}

export const updateThresholds = async (data: ThresholdUpdate): Promise<ThresholdRead> => {
  const r = await api.put<ThresholdRead>('/admin/thresholds', data)
  return r.data
}

// ─── Model Metrics ────────────────────────────────────────────────────────────
export const getMetrics = async (): Promise<MetricsResponse> => {
  const r = await api.get<MetricsResponse>('/metrics')
  return r.data
}

// ─── Simulation ─────────────────────────────────────────────────────────────────────────────────
export const runSimulation = async (batchSize = 20, seed?: number): Promise<SimulationResponse> => {
  const r = await api.get<SimulationResponse>('/simulate', {
    params: { batch_size: batchSize, ...(seed !== undefined ? { seed } : {}) },
  })
  return r.data
}

// ─── Dashboard Stats ──────────────────────────────────────────────────────────────────────────
export const getDashboardStats = async (): Promise<DashboardStats> => {
  const r = await api.get<DashboardStats>('/stats')
  return r.data
}

// ─── Users ───────────────────────────────────────────────────────────────────────────────────
export const getUsers = async (): Promise<UserListItem[]> => {
  const r = await api.get<UserListItem[]>('/users')
  return r.data
}

// ─── LLM Explanations ────────────────────────────────────────────────────────────────────────

export interface ExplainRequest {
  decision_tier: string
  final_score: number
  xgb_score?: number
  if_score?: number
  amount: number
  shap_features?: Array<{
    feature_name: string
    shap_value: number
    feature_value: number
    direction: string
    rank: number
  }>
  behavioral?: Record<string, number | null>
}

export interface ExplainResponse {
  explanation: string
  source: 'ollama' | 'rule_based'
  model?: string
}

export const explainTransaction = async (data: ExplainRequest): Promise<ExplainResponse> => {
  // qwen3:8b cold start can take up to 60s — use 75s timeout
  const r = await api.post<ExplainResponse>('/explain', data, { timeout: 75000 })
  return r.data
}

// ─── CSV Data Import ────────────────────────────────────────────────────────

export interface ValidationError {
  row: number | null
  column: string | null
  message: string
}

export interface ValidateResponse {
  valid: boolean
  file_size_bytes: number
  original_rows: number
  original_cols: number
  duplicate_rows: number
  missing_value_rows: number
  invalid_rows: number
  valid_rows: number
  present_cols: string[]
  missing_required: string[]
  extra_cols: string[]
  errors: ValidationError[]
  warnings: string[]
  preview: Record<string, unknown>[]
  column_stats: Record<string, { min: number; max: number; mean: number; nulls: number }>
}

export interface ImportResponse {
  batch_id: number
  original_rows: number
  duplicate_rows: number
  invalid_rows: number
  valid_rows: number
  imported_rows: number
  behavioral_features: number
  model_features: number
  scored: boolean
  approve_count: number | null
  review_count: number | null
  block_count: number | null
  processing_time_ms: number
  errors: { row: number | null; reason: string }[]
  warnings: string[]
}

export interface ImportBatchSummary {
  id: number
  original_filename: string
  uploaded_by_username: string
  uploaded_by_display_name: string
  original_rows: number
  valid_rows: number
  imported_rows: number
  duplicate_rows: number
  invalid_rows: number
  scored: boolean
  approve_count: number | null
  review_count: number | null
  block_count: number | null
  mode: string
  status: string
  processing_time_ms: number | null
  created_at: string
  completed_at: string | null
}

export const validateCsv = async (file: File): Promise<ValidateResponse> => {
  const form = new FormData()
  form.append('file', file)
  const r = await api.post<ValidateResponse>('/data-import/validate', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  })
  return r.data
}

export const importCsv = async (file: File, score: boolean): Promise<ImportResponse> => {
  const form = new FormData()
  form.append('file', file)
  form.append('score', score ? 'true' : 'false')
  const r = await api.post<ImportResponse>('/data-import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,  // large files may take up to 5 minutes
  })
  return r.data
}

export const getImportHistory = async (): Promise<ImportBatchSummary[]> => {
  const r = await api.get<ImportBatchSummary[]>('/data-import/history')
  return r.data
}

export const deleteImportBatch = async (batchId: number): Promise<{
  deleted: boolean
  batch_id: number
  filename: string
  transactions_deleted: number
}> => {
  const r = await api.delete(`/data-import/${batchId}`)
  return r.data
}

export interface BatchTransaction {
  id: number
  transaction_uuid: string
  synthetic_user_id: string
  amount: number
  final_score: number | null
  xgb_score: number | null
  if_score: number | null
  decision_tier: string | null
  true_label: number | null
  created_at: string
}

export interface BatchTransactionsResponse {
  batch_id: number
  total: number
  page: number
  page_size: number
  total_pages: number
  items: BatchTransaction[]
}

export const getBatchTransactions = async (
  batchId: number,
  page = 1,
  pageSize = 20,
): Promise<BatchTransactionsResponse> => {
  const r = await api.get<BatchTransactionsResponse>(`/data-import/${batchId}/transactions`, {
    params: { page, page_size: pageSize },
  })
  return r.data
}

export interface RescoreResult {
  rescored: boolean
  batch_id: number
  rows_rescored: number
  approve_count: number
  review_count: number
  block_count: number
  processing_time_ms: number
}


export const rescoreBatch = async (batchId: number): Promise<RescoreResult> => {
  const r = await api.post<RescoreResult>(`/data-import/${batchId}/rescore`, null, {
    timeout: 300000, // large batches can take a while
  })
  return r.data
}

// ─── AI Chat Assistant ──────────────────────────────────────────────────────

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  source?: 'pandasai' | 'knowledge_base' | 'rule_based' | 'ollama'
  created_at: string
  error?: boolean
}

export interface ChatRequest {
  message: string
  session_id?: string
}

export interface ChatResponse {
  message: ChatMessage
  session_id: string
}

export const sendChatMessage = async (
  message: string,
  sessionId?: string,
): Promise<ChatResponse> => {
  const r = await api.post<ChatResponse>('/chat', { message, session_id: sessionId }, {
    timeout: 90000,  // PandasAI + Ollama can take up to 90s
  })
  return r.data
}

export const getChatHistory = async (sessionId: string): Promise<ChatMessage[]> => {
  const r = await api.get<ChatMessage[]>('/chat/history', { params: { session_id: sessionId } })
  return r.data
}

export const clearChatHistory = async (sessionId: string): Promise<void> => {
  await api.delete('/chat/history', { params: { session_id: sessionId } })
}

export default api


// src/pages/DataImport.tsx
// Full pipeline wizard for CSV import — validate-first, score-on-import, batch management
import { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Upload, FileText, CheckCircle, XCircle, AlertTriangle, RefreshCw,
  Database, BarChart2, Eye, Clock, Trash2, Shield, Zap, Info,
  ChevronDown, ChevronRight, ExternalLink, RotateCcw, TrendingUp,
  ArrowRight, Check, Loader2, Table2, Activity,
} from 'lucide-react'
import {
  validateCsv, importCsv, getImportHistory, deleteImportBatch,
  getBatchTransactions, rescoreBatch,
  type ValidateResponse, type ImportResponse, type ImportBatchSummary,
  type BatchTransaction,
} from '../lib/api'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}
function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
function fmtNum(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString()
}
function pct(n: number | null | undefined, total: number | null | undefined): string {
  if (!n || !total) return '0%'
  return `${((n / total) * 100).toFixed(1)}%`
}

// ── Pipeline Steps ────────────────────────────────────────────────────────────

const STEPS = ['Upload', 'Validate', 'Import', 'Done'] as const
type Step = typeof STEPS[number]

function StepBar({ current }: { current: Step }) {
  const idx = STEPS.indexOf(current)
  return (
    <div className="flex items-center gap-0 mb-6">
      {STEPS.map((s, i) => {
        const done    = i < idx
        const active  = i === idx
        const pending = i > idx
        return (
          <div key={s} className="flex items-center">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold transition-all duration-300 ${
              done    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' :
              active  ? 'bg-cyan/15 text-cyan border border-cyan/30' :
                        'bg-white/[0.03] text-slate-600 border border-white/[0.06]'
            }`}>
              {done
                ? <Check size={11} />
                : <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] border ${
                    active ? 'border-cyan text-cyan' : 'border-white/10 text-slate-600'
                  }`}>{i + 1}</span>
              }
              {s}
            </div>
            {i < STEPS.length - 1 && (
              <div className={`h-px w-8 transition-colors duration-300 ${i < idx ? 'bg-emerald-500/40' : 'bg-white/[0.06]'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Small sub-components ──────────────────────────────────────────────────────

function StatCard({
  label, value, color = 'text-white', sub,
}: { label: string; value: string | number; color?: string; sub?: string }) {
  return (
    <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-4 text-center">
      <div className={`text-2xl font-bold font-mono ${color}`}>{value}</div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
      {sub && <div className="text-[10px] text-slate-600 mt-0.5">{sub}</div>}
    </div>
  )
}

function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return <span className="text-slate-600 text-xs">—</span>
  const cfg = {
    BLOCK:   'bg-red-500/10 text-red-400 border-red-500/25',
    REVIEW:  'bg-amber-500/10 text-amber-400 border-amber-500/25',
    APPROVE: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25',
  }[tier] ?? 'bg-white/5 text-slate-400 border-white/10'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border ${cfg}`}>
      {tier}
    </span>
  )
}

// ── Column Stats mini-table ───────────────────────────────────────────────────

function ColumnStatsPanel({ stats }: { stats: Record<string, { min: number; max: number; mean: number; nulls: number }> }) {
  const cols = Object.entries(stats).slice(0, 10)
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
        <span className="text-cyan"><Table2 size={14} /></span>
        Column Statistics
        <span className="text-xs text-slate-600 font-normal">First 10 columns</span>
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/5">
              {['Column', 'Min', 'Max', 'Mean', 'Nulls'].map(h => (
                <th key={h} className="py-2 px-3 text-left text-slate-500 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cols.map(([col, s]) => (
              <tr key={col} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                <td className="py-1.5 px-3 font-semibold text-slate-300">{col}</td>
                <td className="py-1.5 px-3 font-mono text-slate-400">{s.min?.toFixed(3)}</td>
                <td className="py-1.5 px-3 font-mono text-slate-400">{s.max?.toFixed(3)}</td>
                <td className="py-1.5 px-3 font-mono text-slate-400">{s.mean?.toFixed(3)}</td>
                <td className="py-1.5 px-3 font-mono text-slate-500">
                  {s.nulls > 0
                    ? <span className="text-amber-400">{s.nulls}</span>
                    : <span className="text-emerald-400/60">0</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Decision Donut ────────────────────────────────────────────────────────────

function DecisionBreakdown({
  approve, review, block, total,
}: { approve: number; review: number; block: number; total: number }) {
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
        <span className="text-cyan"><BarChart2 size={14} /></span>
        Model Decision Breakdown
        <span className="text-xs text-slate-500 font-normal">— scored by the same pipeline as training data</span>
      </h3>
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'APPROVE', count: approve, color: 'emerald', icon: '✓', desc: 'Score < 0.50' },
          { label: 'REVIEW',  count: review,  color: 'amber',   icon: '⚠', desc: 'Score 0.50–0.85' },
          { label: 'BLOCK',   count: block,   color: 'red',     icon: '✕', desc: 'Score > 0.85' },
        ].map(({ label, count, color, icon, desc }) => (
          <div
            key={label}
            className={`p-4 rounded-xl border border-${color}-500/15 bg-${color}-500/5 text-center space-y-1.5`}
          >
            <div className={`text-3xl font-extrabold text-${color}-400`}>{fmtNum(count)}</div>
            <div className={`text-xs font-bold text-${color}-400/80`}>{icon} {label}</div>
            <div className={`text-[10px] text-${color}-400/50`}>{pct(count, total)}</div>
            <div className="text-[10px] text-slate-600">{desc}</div>
          </div>
        ))}
      </div>
      {/* Score bar */}
      <div className="mt-4">
        <div className="flex h-2 rounded-full overflow-hidden gap-px">
          <div
            className="bg-emerald-500/60 transition-all duration-700"
            style={{ width: `${pct(approve, total)}` }}
          />
          <div
            className="bg-amber-500/60 transition-all duration-700"
            style={{ width: `${pct(review, total)}` }}
          />
          <div
            className="bg-red-500/60 transition-all duration-700"
            style={{ width: `${pct(block, total)}` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-slate-600 mt-1">
          <span>{pct(approve, total)} Approved</span>
          <span>{pct(review, total)} Review</span>
          <span>{pct(block, total)} Blocked</span>
        </div>
      </div>
    </div>
  )
}

// ── Inline batch transaction viewer ──────────────────────────────────────────

function BatchTransactionInlineView({ batchId }: { batchId: number }) {
  const [data, setData]       = useState<{ items: BatchTransaction[]; total: number } | null>(null)
  const [page, setPage]       = useState(1)
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState<string | null>(null)

  const load = useCallback(async (p: number) => {
    setLoading(true); setErr(null)
    try {
      const r = await getBatchTransactions(batchId, p, 15)
      setData({ items: r.items, total: r.total })
      setPage(p)
    } catch (e: unknown) {
      setErr((e as { message?: string })?.message || 'Failed to load transactions')
    } finally {
      setLoading(false)
    }
  }, [batchId])

  useEffect(() => { load(1) }, [load])

  if (loading && !data) return (
    <div className="flex items-center gap-2 text-slate-500 text-xs py-6 justify-center">
      <RefreshCw size={12} className="animate-spin text-cyan" /> Loading transactions…
    </div>
  )
  if (err) return <div className="text-red-400 text-xs py-4 text-center">{err}</div>
  if (!data) return null

  return (
    <div className="space-y-3">
      <div className="text-xs text-slate-500 flex items-center justify-between px-1">
        <span>{fmtNum(data.total)} transactions in this batch</span>
        {loading && <RefreshCw size={10} className="animate-spin text-cyan" />}
      </div>
      <div className="overflow-x-auto rounded-xl border border-white/[0.06]">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/5 bg-white/[0.02]">
              {['#', 'User', 'Amount', 'XGB', 'IF', 'Fused', 'Decision', 'Ground Truth'].map(h => (
                <th key={h} className="py-2 px-3 text-left text-slate-500 font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.map(tx => (
              <tr key={tx.id} className="border-b border-white/[0.025] hover:bg-white/[0.02]">
                <td className="py-1.5 px-3 font-mono text-slate-600">{tx.id}</td>
                <td className="py-1.5 px-3 font-mono text-slate-400 max-w-[90px] truncate">{tx.synthetic_user_id}</td>
                <td className="py-1.5 px-3 font-bold text-white">${tx.amount.toFixed(2)}</td>
                <td className="py-1.5 px-3 font-mono text-slate-500">{tx.xgb_score?.toFixed(3) ?? '—'}</td>
                <td className="py-1.5 px-3 font-mono text-slate-500">{tx.if_score?.toFixed(3) ?? '—'}</td>
                <td className="py-1.5 px-3 font-mono text-slate-300">{tx.final_score?.toFixed(3) ?? '—'}</td>
                <td className="py-1.5 px-3"><TierBadge tier={tx.decision_tier} /></td>
                <td className="py-1.5 px-3">
                  {tx.true_label === null ? <span className="text-slate-700">—</span>
                    : tx.true_label === 1
                      ? <span className="text-red-400 text-[10px] font-bold">● Fraud</span>
                      : <span className="text-emerald-400/70 text-[10px] font-bold">● Legit</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.total > 15 && (
        <div className="flex items-center justify-between px-1">
          <button
            onClick={() => load(page - 1)} disabled={page <= 1 || loading}
            className="btn-ghost py-1 px-3 text-xs disabled:opacity-30"
          >← Prev</button>
          <span className="text-xs text-slate-600">Page {page} · {fmtNum(data.total)} rows</span>
          <button
            onClick={() => load(page + 1)} disabled={page * 15 >= data.total || loading}
            className="btn-ghost py-1 px-3 text-xs disabled:opacity-30"
          >Next →</button>
        </div>
      )}
    </div>
  )
}

// ── History table row ─────────────────────────────────────────────────────────

function BatchRow({
  batch,
  onDelete,
  onRescore,
  deleting,
  rescoring,
  navigate,
}: {
  batch: ImportBatchSummary
  onDelete: () => void
  onRescore: () => void
  deleting: boolean
  rescoring: boolean
  navigate: (path: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  const statusStyle = {
    completed:      'text-emerald-400',
    failed:         'text-red-400',
    validated_only: 'text-cyan',
  }[batch.status] ?? 'text-amber-400'

  return (
    <>
      <tr className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors group">
        {/* Expand toggle */}
        <td className="py-3 px-3">
          <button
            onClick={() => setExpanded(e => !e)}
            className="p-1 rounded text-slate-600 hover:text-white transition-colors"
            title="Show transactions"
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        </td>

        {/* File */}
        <td className="py-3 px-3">
          <div className="flex items-center gap-2">
            <FileText size={12} className="text-slate-600 flex-shrink-0" />
            <span className="text-white font-medium max-w-[150px] truncate text-sm" title={batch.original_filename}>
              {batch.original_filename}
            </span>
          </div>
          <div className="text-[10px] text-slate-600 mt-0.5 pl-5">
            #{batch.id} · {new Date(batch.created_at).toLocaleString()}
          </div>
        </td>

        {/* Rows */}
        <td className="py-3 px-3 text-right font-mono text-sm text-slate-400">{fmtNum(batch.original_rows)}</td>
        <td className="py-3 px-3 text-right font-mono text-sm text-emerald-400">{fmtNum(batch.imported_rows)}</td>

        {/* Decision breakdown */}
        <td className="py-3 px-3">
          {batch.scored ? (
            <div className="flex items-center gap-1 justify-center flex-wrap">
              <span className="text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                ✓ {batch.approve_count ?? 0}
              </span>
              <span className="text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20 px-1.5 py-0.5 rounded">
                ⚠ {batch.review_count ?? 0}
              </span>
              <span className="text-[10px] font-mono bg-red-500/10 text-red-400 border border-red-500/20 px-1.5 py-0.5 rounded">
                ✕ {batch.block_count ?? 0}
              </span>
            </div>
          ) : (
            <span className="text-xs text-slate-600 block text-center">Not scored</span>
          )}
        </td>

        {/* Status */}
        <td className="py-3 px-3">
          <span className={`text-xs font-semibold ${statusStyle}`}>
            {batch.status.replace('_', ' ').toUpperCase()}
          </span>
        </td>

        {/* Uploader */}
        <td className="py-3 px-3 text-xs text-slate-400">{batch.uploaded_by_display_name}</td>

        {/* Actions */}
        <td className="py-3 px-3">
          <div className="flex items-center gap-1 justify-end">
            {/* View in Dashboard */}
            <button
              onClick={() => navigate(`/?source=imported&batch=${batch.id}`)}
              title="View these transactions in Live Dashboard"
              className="p-1.5 rounded-lg text-slate-600 hover:text-cyan hover:bg-cyan/10 transition-colors"
            >
              <ExternalLink size={12} />
            </button>

            {/* Rescore */}
            {batch.status === 'completed' && (
              <button
                onClick={onRescore}
                disabled={rescoring}
                title="Re-run scoring with current thresholds"
                className="p-1.5 rounded-lg text-slate-600 hover:text-amber-400 hover:bg-amber-500/10 transition-colors disabled:opacity-40"
              >
                {rescoring ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
              </button>
            )}

            {/* Delete */}
            <button
              onClick={onDelete}
              disabled={deleting}
              title={`Delete batch and remove ${fmtNum(batch.imported_rows)} transactions`}
              className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-40"
            >
              {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
            </button>
          </div>
        </td>
      </tr>

      {/* Inline expanded transactions */}
      {expanded && (
        <tr className="border-b border-white/[0.03]">
          <td colSpan={8} className="bg-white/[0.015] px-6 py-4">
            <BatchTransactionInlineView batchId={batch.id} />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DataImportPage() {
  const navigate = useNavigate()

  const [step, setStep]               = useState<Step>('Upload')
  const [file, setFile]               = useState<File | null>(null)
  const [dragging, setDragging]       = useState(false)
  const [loading, setLoading]         = useState<false | 'validating' | 'importing'>(false)
  const [validation, setValidation]   = useState<ValidateResponse | null>(null)
  const [importResult, setImportResult] = useState<ImportResponse | null>(null)
  const [error, setError]             = useState<string | null>(null)

  const [activeTab, setActiveTab]     = useState<'import' | 'history'>('import')
  const [history, setHistory]         = useState<ImportBatchSummary[] | null>(null)
  const [deletingId, setDeletingId]   = useState<number | null>(null)
  const [rescoringId, setRescoringId] = useState<number | null>(null)
  const [showColStats, setShowColStats] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)

  // ── File selection ──
  const selectFile = useCallback((f: File) => {
    setFile(f); setValidation(null); setImportResult(null)
    setError(null); setStep('Upload')
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) selectFile(f)
  }, [selectFile])

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) selectFile(f)
  }

  const reset = () => {
    setFile(null); setValidation(null); setImportResult(null)
    setError(null); setStep('Upload')
    if (inputRef.current) inputRef.current.value = ''
  }

  // ── Validate ──
  const handleValidate = async () => {
    if (!file) return
    setLoading('validating'); setError(null); setImportResult(null)
    try {
      const r = await validateCsv(file)
      setValidation(r)
      setStep('Validate')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail || (err as { message?: string })?.message || 'Validation failed'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally {
      setLoading(false)
    }
  }

  // ── Import ──
  const handleImport = async () => {
    if (!file || !validation?.valid) return
    setLoading('importing'); setError(null)
    try {
      const r = await importCsv(file, true)   // always score=true for full pipeline
      setImportResult(r); setStep('Done')
      // Notify dashboard to refresh
      window.dispatchEvent(new CustomEvent('fraudshield:data_changed', {
        detail: { reason: 'batch_imported', batch_id: r.batch_id },
      }))
    } catch (err: unknown) {
      const raw = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      if (raw && typeof raw === 'object' && (raw as { message?: string }).message) {
        setError((raw as { message: string }).message)
      } else {
        setError(typeof raw === 'string' ? raw : (err as { message?: string })?.message || 'Import failed')
      }
    } finally {
      setLoading(false)
    }
  }

  // ── History ──
  const loadHistory = async () => {
    setActiveTab('history')
    try {
      setHistory(null)
      const h = await getImportHistory()
      setHistory(h)
    } catch {
      setHistory([])
    }
  }

  // ── Delete batch ──
  const handleDeleteBatch = async (batch: ImportBatchSummary) => {
    const confirmed = window.confirm(
      `Delete "${batch.original_filename}"?\n\nThis will permanently remove ${fmtNum(batch.imported_rows)} imported transactions from the system. The Live Dashboard will update immediately. This cannot be undone.`
    )
    if (!confirmed) return
    setDeletingId(batch.id)
    try {
      await deleteImportBatch(batch.id)
      setHistory(prev => prev ? prev.filter(b => b.id !== batch.id) : prev)
      window.dispatchEvent(new CustomEvent('fraudshield:data_changed', {
        detail: { reason: 'batch_deleted', batch_id: batch.id },
      }))
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err as { message?: string })?.message || 'Delete failed'
      alert(`Failed to delete batch: ${msg}`)
    } finally {
      setDeletingId(null)
    }
  }

  // ── Rescore batch ──
  const handleRescore = async (batch: ImportBatchSummary) => {
    setRescoringId(batch.id)
    try {
      const r = await rescoreBatch(batch.id)
      // Refresh history to show updated counts
      const h = await getImportHistory()
      setHistory(h)
      window.dispatchEvent(new CustomEvent('fraudshield:data_changed', {
        detail: { reason: 'batch_rescored', batch_id: batch.id },
      }))
      alert(`Rescored ${fmtNum(r.rows_rescored)} transactions in ${fmtMs(r.processing_time_ms)}.\n✓ ${r.approve_count} Approve  ⚠ ${r.review_count} Review  ✕ ${r.block_count} Block`)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err as { message?: string })?.message || 'Rescore failed'
      alert(`Rescore failed: ${msg}`)
    } finally {
      setRescoringId(null)
    }
  }

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="p-6 space-y-5 animate-fade-in">

      {/* Header */}
      <div>
        <h1 className="section-title">
          <div className="p-2 rounded-xl bg-cyan/10 text-cyan"><Upload size={18} /></div>
          Data Import
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Import transaction CSV datasets through the same preprocessing pipeline used during model training.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-2 border-b border-white/[0.06]">
        {(['import', 'history'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => tab === 'history' ? loadHistory() : setActiveTab('import')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
              activeTab === tab
                ? 'border-cyan text-cyan'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab === 'import' ? 'Import Data' : 'Import History'}
          </button>
        ))}
      </div>

      {/* ══════════════════ IMPORT TAB ══════════════════ */}
      {activeTab === 'import' && (
        <div className="space-y-5">

          {/* Pipeline info banner */}
          <div className="flex items-start gap-3 bg-cyan/5 border border-cyan/15 rounded-xl p-4">
            <Shield size={15} className="text-cyan flex-shrink-0 mt-0.5" />
            <p className="text-xs text-slate-400 leading-relaxed">
              <span className="text-white font-medium">Training-serving consistency guaranteed.</span>{' '}
              Imported data passes through the{' '}
              <span className="text-cyan">exact same preprocessing pipeline</span> used to train the model —
              using <code className="text-cyan/80 bg-white/5 px-1 rounded text-[10px]">scaler.transform()</code>{' '}
              (never <code className="text-red-400/70 bg-white/5 px-1 rounded text-[10px]">fit()</code>),
              behavioral feature engineering, and the hybrid XGBoost+IF scorer.
              Deleting an import batch removes all its transactions from the Live Dashboard instantly.
            </p>
          </div>

          {/* Step bar */}
          <StepBar current={step} />

          {/* Error */}
          {error && (
            <div className="flex items-start gap-3 bg-red-500/8 border border-red-500/20 rounded-xl p-4">
              <XCircle size={15} className="text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-red-400">Operation failed</p>
                <p className="text-xs text-red-400/80 mt-1">{error}</p>
              </div>
            </div>
          )}

          {/* ── STEP: Upload ── */}
          {step === 'Upload' && (
            <div className="space-y-4">
              {!file ? (
                <div
                  onDragOver={e => { e.preventDefault(); setDragging(true) }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                  onClick={() => inputRef.current?.click()}
                  className={`
                    glass-card border-2 border-dashed rounded-2xl p-14 text-center cursor-pointer
                    transition-all duration-200
                    ${dragging
                      ? 'border-cyan/60 bg-cyan/5'
                      : 'border-white/10 hover:border-cyan/30 hover:bg-white/[0.02]'}
                  `}
                >
                  <div className="flex flex-col items-center gap-4">
                    <div className={`p-5 rounded-2xl transition-colors ${dragging ? 'bg-cyan/20' : 'bg-white/5'}`}>
                      <Upload size={36} className={dragging ? 'text-cyan' : 'text-slate-500'} />
                    </div>
                    <div>
                      <p className="text-white font-semibold text-lg">
                        {dragging ? 'Drop CSV file here' : 'Drag & drop CSV file'}
                      </p>
                      <p className="text-xs text-slate-500 mt-1">or click to browse — CSV only · max 100 MB</p>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap justify-center text-xs text-slate-600">
                      {['Time', 'Amount', 'V1–V28'].map(c => (
                        <span key={c} className="px-2 py-0.5 bg-white/5 rounded border border-white/5">{c}</span>
                      ))}
                      <span className="text-slate-700">required columns</span>
                    </div>
                  </div>
                  <input ref={inputRef} type="file" accept=".csv" className="hidden" onChange={onFileInput} />
                </div>
              ) : (
                <div className="glass-card p-5 space-y-4">
                  {/* File info */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="p-2.5 bg-cyan/10 rounded-xl">
                        <FileText size={20} className="text-cyan" />
                      </div>
                      <div>
                        <p className="text-base font-semibold text-white">{file.name}</p>
                        <p className="text-xs text-slate-500">{fmtBytes(file.size)}</p>
                      </div>
                    </div>
                    <button onClick={reset} className="btn-ghost p-2 text-slate-500 hover:text-red-400">
                      <Trash2 size={15} />
                    </button>
                  </div>

                  {/* Mandatory validate step */}
                  <div className="rounded-xl bg-amber-500/5 border border-amber-500/15 p-3.5 flex items-start gap-3">
                    <Info size={14} className="text-amber-400 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-amber-300 font-medium">Validate before importing</p>
                      <p className="text-xs text-amber-400/70 mt-0.5">
                        Run validation first to check schema, detect duplicates, and preview the data before committing to the database.
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 pt-1">
                    <button
                      onClick={handleValidate}
                      disabled={loading !== false}
                      className="flex items-center gap-2 text-sm py-2.5 px-6 bg-cyan text-navy font-semibold rounded-xl hover:bg-cyan/90 transition-colors disabled:opacity-50"
                    >
                      {loading === 'validating'
                        ? <><RefreshCw size={14} className="animate-spin" /> Validating…</>
                        : <><Eye size={14} /> Validate File</>
                      }
                    </button>
                    <button onClick={reset} className="btn-ghost py-2 px-4 text-sm">Remove</button>
                  </div>

                  {loading === 'validating' && (
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <RefreshCw size={11} className="animate-spin text-cyan" />
                      Checking schema, duplicates, and data quality…
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── STEP: Validate result ── */}
          {step === 'Validate' && validation && !importResult && (
            <div className="space-y-4">
              {/* Status banner */}
              <div className={`flex items-center gap-3 rounded-xl p-4 border ${
                validation.valid
                  ? 'bg-emerald-500/8 border-emerald-500/20'
                  : 'bg-red-500/8 border-red-500/20'
              }`}>
                {validation.valid
                  ? <CheckCircle size={16} className="text-emerald-400 flex-shrink-0" />
                  : <XCircle size={16} className="text-red-400 flex-shrink-0" />}
                <div className="flex-1">
                  <p className={`text-sm font-semibold ${validation.valid ? 'text-emerald-400' : 'text-red-400'}`}>
                    {validation.valid
                      ? `CSV is valid — ${fmtNum(validation.valid_rows)} rows ready to import`
                      : 'CSV validation failed — fix errors before importing'}
                  </p>
                  {validation.missing_required.length > 0 && (
                    <p className="text-xs text-red-400/80 mt-1">
                      Missing required columns: {validation.missing_required.join(', ')}
                    </p>
                  )}
                </div>
              </div>

              {/* Stats grid */}
              <div className="grid grid-cols-4 gap-3">
                <StatCard label="Total Rows"    value={fmtNum(validation.original_rows)} />
                <StatCard label="Valid Rows"    value={fmtNum(validation.valid_rows)}    color="text-emerald-400" />
                <StatCard label="Duplicates"    value={fmtNum(validation.duplicate_rows)} color={validation.duplicate_rows > 0 ? 'text-amber-400' : 'text-white'} />
                <StatCard label="Invalid Rows"  value={fmtNum(validation.invalid_rows)}  color={validation.invalid_rows > 0 ? 'text-red-400' : 'text-white'} />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <StatCard label="Columns Found"    value={validation.original_cols} />
                <StatCard label="Missing Values"   value={fmtNum(validation.missing_value_rows)} color={validation.missing_value_rows > 0 ? 'text-amber-400' : 'text-white'} />
                <StatCard label="File Size"        value={fmtBytes(validation.file_size_bytes)} />
              </div>

              {/* Warnings */}
              {validation.warnings.length > 0 && (
                <div className="bg-amber-500/8 border border-amber-500/20 rounded-xl p-4 space-y-1">
                  {validation.warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs text-amber-400/90">
                      <AlertTriangle size={11} className="mt-0.5 flex-shrink-0" /> {w}
                    </div>
                  ))}
                </div>
              )}

              {/* Errors */}
              {validation.errors.length > 0 && (
                <div className="glass-card p-4">
                  <h3 className="text-xs font-semibold text-red-400 flex items-center gap-2 mb-3">
                    <XCircle size={13} /> Validation Errors <span className="text-slate-600 font-normal">({validation.errors.length})</span>
                  </h3>
                  <div className="space-y-2 max-h-40 overflow-y-auto">
                    {validation.errors.slice(0, 50).map((e, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        {e.row && <span className="font-mono text-slate-600 flex-shrink-0 w-16">Row {e.row}</span>}
                        <span className="text-red-400/90">{e.message}</span>
                      </div>
                    ))}
                    {validation.errors.length > 50 && (
                      <p className="text-xs text-slate-600 text-center pt-2">…and {validation.errors.length - 50} more</p>
                    )}
                  </div>
                </div>
              )}

              {/* Column stats toggle */}
              {Object.keys(validation.column_stats ?? {}).length > 0 && (
                <button
                  onClick={() => setShowColStats(v => !v)}
                  className="btn-ghost flex items-center gap-2 text-xs py-2 px-3"
                >
                  {showColStats ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  {showColStats ? 'Hide' : 'Show'} Column Statistics
                </button>
              )}
              {showColStats && validation.column_stats && (
                <ColumnStatsPanel stats={validation.column_stats} />
              )}

              {/* Preview table */}
              {validation.preview.length > 0 && (
                <div className="glass-card p-5">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
                    <span className="text-cyan"><Eye size={14} /></span>
                    Data Preview
                    <span className="text-xs text-slate-600 font-normal">First {validation.preview.length} rows</span>
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-white/5">
                          {Object.keys(validation.preview[0]).slice(0, 12).map(col => (
                            <th key={col} className="py-2 px-3 text-left text-slate-500 font-medium whitespace-nowrap">{col}</th>
                          ))}
                          {Object.keys(validation.preview[0]).length > 12 && (
                            <th className="py-2 px-3 text-left text-slate-600">…+{Object.keys(validation.preview[0]).length - 12} cols</th>
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {validation.preview.slice(0, 8).map((row, i) => (
                          <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                            {Object.keys(validation.preview[0]).slice(0, 12).map(col => (
                              <td key={col} className="py-1.5 px-3 font-mono text-slate-400 whitespace-nowrap">
                                {String(row[col] ?? '—').slice(0, 12)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Action buttons */}
              {validation.valid ? (
                <div className="flex gap-3 pt-1">
                  <button
                    onClick={handleImport}
                    disabled={loading !== false}
                    className="flex items-center gap-2 text-sm py-2.5 px-7 bg-cyan text-navy font-semibold rounded-xl hover:bg-cyan/90 transition-colors disabled:opacity-50"
                  >
                    {loading === 'importing'
                      ? <><RefreshCw size={14} className="animate-spin" /> Importing…</>
                      : <><Database size={14} /> Import & Score <ArrowRight size={13} /></>
                    }
                  </button>
                  <button onClick={reset} className="btn-ghost py-2 px-4 text-sm">Start Over</button>
                  {loading === 'importing' && (
                    <div className="flex items-center gap-2 text-xs text-slate-500 ml-2">
                      <Zap size={11} className="text-cyan animate-pulse" />
                      Running through preprocessing pipeline + XGBoost+IF scorer…
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex gap-3 pt-1">
                  <button onClick={reset} className="btn-ghost py-2 px-4 text-sm flex items-center gap-2">
                    <Upload size={13} /> Try a Different File
                  </button>
                </div>
              )}
            </div>
          )}

          {/* ── STEP: Done ── */}
          {step === 'Done' && importResult && (
            <div className="space-y-4">
              {/* Success banner */}
              <div className="flex items-center gap-3 bg-emerald-500/8 border border-emerald-500/20 rounded-xl p-4">
                <CheckCircle size={18} className="text-emerald-400 flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-sm font-semibold text-emerald-400">Import Successful</p>
                  <p className="text-xs text-emerald-400/70 mt-0.5">
                    Batch #{importResult.batch_id} · processed in {fmtMs(importResult.processing_time_ms)} ·{' '}
                    {fmtNum(importResult.imported_rows)} transactions now in the Live Dashboard
                  </p>
                </div>
                <button
                  onClick={() => navigate(`/dashboard?source=imported&batch=${importResult.batch_id}`)}
                  className="flex items-center gap-1.5 text-xs text-cyan border border-cyan/30 bg-cyan/10 px-3 py-1.5 rounded-lg hover:bg-cyan/20 transition-colors"
                >
                  <Activity size={11} /> View in Dashboard <ExternalLink size={10} />
                </button>
              </div>

              {/* Row counts */}
              <div className="grid grid-cols-4 gap-3">
                <StatCard label="Original Rows"      value={fmtNum(importResult.original_rows)} />
                <StatCard label="Duplicates Removed" value={fmtNum(importResult.duplicate_rows)} color="text-amber-400" />
                <StatCard label="Invalid Rejected"   value={fmtNum(importResult.invalid_rows)} color={importResult.invalid_rows > 0 ? 'text-red-400' : 'text-white'} />
                <StatCard label="Rows Imported"      value={fmtNum(importResult.imported_rows)} color="text-emerald-400" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <StatCard label="Behavioral Features" value={importResult.behavioral_features} color="text-cyan" sub="tx_freq, deviation, etc." />
                <StatCard label="Model Features"      value={importResult.model_features}      color="text-cyan" sub="V1–V28 + behavioral" />
                <StatCard label="Processing Time"     value={fmtMs(importResult.processing_time_ms)} />
              </div>

              {/* Decision breakdown */}
              {importResult.scored && (
                <DecisionBreakdown
                  approve={importResult.approve_count ?? 0}
                  review={importResult.review_count ?? 0}
                  block={importResult.block_count ?? 0}
                  total={importResult.imported_rows}
                />
              )}

              {/* Model pipeline confirmation */}
              <div className="flex items-start gap-3 bg-cyan/5 border border-cyan/15 rounded-xl p-4">
                <TrendingUp size={14} className="text-cyan flex-shrink-0 mt-0.5" />
                <div className="text-xs text-slate-400 leading-relaxed">
                  <span className="text-cyan font-medium">Pipeline identical to training.</span>{' '}
                  These {fmtNum(importResult.imported_rows)} transactions were preprocessed with the saved{' '}
                  <code className="text-cyan/80 bg-white/5 px-1 rounded">scaler.transform()</code>,
                  had 6 behavioral features computed, then were scored through the hybrid
                  XGBoost+Isolation Forest pipeline — the exact same path as the training data.
                  The decisions above are the model's real outputs on this new data.
                </div>
              </div>

              {/* Warnings */}
              {importResult.warnings.length > 0 && (
                <div className="bg-amber-500/8 border border-amber-500/20 rounded-xl p-4 space-y-1">
                  {importResult.warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs text-amber-400/90">
                      <AlertTriangle size={11} className="mt-0.5 flex-shrink-0" /> {w}
                    </div>
                  ))}
                </div>
              )}

              <div className="flex gap-3">
                <button onClick={reset} className="btn-ghost flex items-center gap-2 text-sm py-2 px-4">
                  <Upload size={13} /> Import Another File
                </button>
                <button onClick={loadHistory} className="btn-ghost flex items-center gap-2 text-sm py-2 px-4">
                  <Clock size={13} /> View Import History
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ══════════════════ HISTORY TAB ══════════════════ */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <span className="text-cyan"><Clock size={14} /></span>
                Import History
                <span className="text-xs text-slate-600 font-normal">Click a row to see its transactions · Delete removes rows from the dashboard</span>
              </h2>
            </div>
            <button onClick={loadHistory} className="btn-ghost p-2" title="Refresh history">
              <RefreshCw size={14} />
            </button>
          </div>

          {history === null ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm p-8 justify-center">
              <RefreshCw size={14} className="animate-spin" /> Loading…
            </div>
          ) : history.length === 0 ? (
            <div className="glass-card p-12 text-center">
              <Database size={24} className="text-slate-600 mx-auto mb-3" />
              <p className="text-slate-500 text-sm">No imports yet</p>
              <p className="text-slate-600 text-xs mt-1">Upload a CSV file to get started</p>
            </div>
          ) : (
            <div className="glass-card overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5 text-xs text-slate-500">
                    <th className="py-3 px-3 w-8"></th>
                    <th className="py-3 px-3 text-left">File</th>
                    <th className="py-3 px-3 text-right">Rows</th>
                    <th className="py-3 px-3 text-right">Imported</th>
                    <th className="py-3 px-3 text-center">Decisions</th>
                    <th className="py-3 px-3 text-left">Status</th>
                    <th className="py-3 px-3 text-left">Uploader</th>
                    <th className="py-3 px-3 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map(b => (
                    <BatchRow
                      key={b.id}
                      batch={b}
                      onDelete={() => handleDeleteBatch(b)}
                      onRescore={() => handleRescore(b)}
                      deleting={deletingId === b.id}
                      rescoring={rescoringId === b.id}
                      navigate={navigate}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

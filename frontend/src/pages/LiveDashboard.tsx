// src/pages/LiveDashboard.tsx
import { useState, useEffect, useCallback, useRef, useReducer } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Play, RefreshCw, Activity, ShieldX, Eye, CheckCircle,
  Info, Brain, AlertTriangle, TrendingUp,
} from 'lucide-react'
import { getTransactions, getTransaction, runSimulation, getDashboardStats } from '../lib/api'
import { MOCK_TRANSACTIONS, MOCK_STATS, getShapForTx } from '../lib/mockData'
import type { TransactionListItem, ShapFeature, DashboardStats } from '../types'
import TierBadge from '../components/TierBadge'
import ScoreBar from '../components/ScoreBar'
import ShapTooltip from '../components/ShapTooltip'

type ShapCache = Record<number, ShapFeature[] | 'loading' | 'none'>
const EMPTY_STATS: DashboardStats = { total: 0, block: 0, review: 0, approve: 0, pending_review: 0 }

// Source types for filter
type SourceFilter = '' | 'simulation' | 'live' | 'imported'

// ── Ground truth badge ──────────────────────────────────────────
function TruthBadge({ label }: { label: number | null | undefined }) {
  if (label === null || label === undefined) return <span className="text-slate-700 text-xs">—</span>
  if (label === 1) return <span className="badge-fraud">● Fraud</span>
  return <span className="badge-legit">● Legit</span>
}

// ── Stat card ───────────────────────────────────────────────────
function StatCard({
  label, value, icon, colorClass, subtitle,
}: { label: string; value: number; icon: React.ReactNode; colorClass: string; subtitle?: string }) {
  return (
    <div className="metric-card group hover:scale-[1.02] transition-transform duration-200">
      <div className="flex items-center justify-between">
        <div className={`p-2 rounded-xl ${colorClass}/10 ${colorClass} flex-shrink-0`}>{icon}</div>
      </div>
      <div className={`text-3xl font-extrabold tracking-tight ${colorClass} animate-count-up`}>
        {value.toLocaleString()}
      </div>
      <div className="text-slate-500 text-xs font-medium">{label}</div>
      {subtitle && <div className="text-xs mt-0.5 opacity-70" style={{ color: 'inherit' }}>{subtitle}</div>}
    </div>
  )
}

export default function LiveDashboard() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // Read import_batch_id from URL query (set by DataImport "View in Dashboard" button)
  const urlBatchId = searchParams.get('batch') ? Number(searchParams.get('batch')) : null
  const urlSource  = (searchParams.get('source') ?? '') as SourceFilter

  const [transactions, setTransactions] = useState<TransactionListItem[]>([])
  const [stats, setStats] = useState<DashboardStats>(EMPTY_STATS)
  const [loading, setLoading] = useState(false)
  const [simulating, setSimulating] = useState(false)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filterTier, setFilterTier] = useState('')
  const [filterSource, setFilterSource] = useState<SourceFilter>(urlSource)
  const [filterBatchId, setFilterBatchId] = useState<number | null>(urlBatchId)
  const [isDemoMode, setIsDemoMode] = useState(false)

  const shapCacheRef = useRef<ShapCache>({})
  const [, forceShapRender] = useReducer((x: number) => x + 1, 0)
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchStats = useCallback(async () => {
    try {
      const data = await getDashboardStats()
      setStats(data)
      setIsDemoMode(false)
    } catch {
      setStats(MOCK_STATS)
      setIsDemoMode(true)
    }
  }, [])

  const fetchTransactions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, unknown> = { page: 1, page_size: 50 }
      if (filterTier)    params.decision_tier   = filterTier
      if (filterSource)  params.source          = filterSource
      if (filterBatchId) params.import_batch_id = filterBatchId
      const data = await getTransactions(params as Parameters<typeof getTransactions>[0])
      setTransactions(data.items)
      setLastUpdate(new Date())
      setIsDemoMode(false)
      // Pre-populate SHAP for all loaded transactions (lazy fetch in background)
      data.items.forEach(tx => {
        if (shapCacheRef.current[tx.id] === undefined) {
          shapCacheRef.current[tx.id] = 'loading'
          getTransaction(tx.id)
            .then(detail => {
              shapCacheRef.current[tx.id] = detail.shap_explanations?.length
                ? detail.shap_explanations
                : getShapForTx(tx.id)
              forceShapRender()
            })
            .catch(() => {
              shapCacheRef.current[tx.id] = getShapForTx(tx.id)
              forceShapRender()
            })
        }
      })
    } catch {
      // Backend offline — show demo data
      const filtered = filterTier
        ? MOCK_TRANSACTIONS.filter(t => t.decision_tier === filterTier)
        : MOCK_TRANSACTIONS
      setTransactions(filtered)
      setLastUpdate(new Date())
      setIsDemoMode(true)
      // Pre-populate SHAP cache for ALL demo transactions immediately
      filtered.forEach(tx => {
        shapCacheRef.current[tx.id] = getShapForTx(tx.id)
      })
      forceShapRender()
    } finally {
      setLoading(false)
    }
  }, [filterTier, filterSource, filterBatchId])

  const handleSimulate = async () => {
    setSimulating(true)
    setError(null)
    try {
      await runSimulation(20)
      await Promise.all([fetchTransactions(), fetchStats()])
    } catch (err: any) {
      setError(
        err.response?.data?.detail ||
        'Simulation failed — backend must be running with ML models loaded. See the offline banner above.'
      )
    } finally {
      setSimulating(false)
    }
  }

  useEffect(() => { fetchTransactions(); fetchStats() }, [fetchTransactions, fetchStats])

  // Refresh when another page (e.g. DataImport) deletes a batch
  useEffect(() => {
    const handleDataChanged = () => {
      fetchStats()
      fetchTransactions()
    }
    window.addEventListener('fraudshield:data_changed', handleDataChanged)
    return () => window.removeEventListener('fraudshield:data_changed', handleDataChanged)
  }, [fetchStats, fetchTransactions])


  const handleRowMouseEnter = useCallback((tx: TransactionListItem) => {
    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current)
    hoverTimeoutRef.current = setTimeout(async () => {
      setHoveredId(tx.id)
      if (shapCacheRef.current[tx.id] !== undefined) return
      shapCacheRef.current[tx.id] = 'loading'
      forceShapRender()
      try {
        const detail = await getTransaction(tx.id)
        shapCacheRef.current[tx.id] = detail.shap_explanations?.length
          ? detail.shap_explanations
          : 'none'
      } catch {
        shapCacheRef.current[tx.id] = getShapForTx(tx.id) // fallback to mock
      }
      forceShapRender()
    }, 150)
  }, [])

  const handleRowMouseLeave = useCallback(() => {
    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current)
    setHoveredId(null)
  }, [])

  const getCached = (id: number) => shapCacheRef.current[id]

  const getTopReason = (txId: number): { label: string; isRisk: boolean } | null => {
    const cached = getCached(txId)
    if (!cached || cached === 'loading' || cached === 'none') return null
    const top = [...cached].sort((a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value))[0]
    if (!top) return null
    const name = top.feature_name
      .replace('amount_deviation_z', 'Amt Z-Score')
      .replace('time_of_day_risk', 'Night Risk')
      .replace('velocity_change', 'Velocity ↑')
      .replace('location_entropy', 'New Device')
      .replace('tx_freq_1h', 'Freq/1h')
      .replace('tx_freq_24h', 'Freq/24h')
    return { label: name, isRisk: top.shap_value > 0 }
  }

  const tierConfig = {
    BLOCK:  { color: 'text-red-400',     bg: 'text-red-500' },
    REVIEW: { color: 'text-amber-400',   bg: 'text-amber-500' },
    APPROVE:{ color: 'text-emerald-400', bg: 'text-emerald-500' },
  }

  return (
    <div className="p-6 space-y-5 animate-fade-in">
      {/* Header */}
      <div className="section-header">
        <div>
          <h1 className="section-title">
            <div className="p-2 rounded-xl bg-cyan/10 text-cyan"><Activity size={18} /></div>
            Live Transaction Monitor
          </h1>
          <p className="text-slate-600 text-sm mt-1.5">
            Real-time fraud detection · Hybrid XGBoost + Isolation Forest ·{' '}
            {isDemoMode && <span className="text-amber-500 font-medium">Demo Data</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdate && (
            <span className="text-slate-600 text-xs hidden sm:block">
              Updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={() => { fetchTransactions(); fetchStats() }}
            disabled={loading}
            className="btn-ghost flex items-center gap-2 py-2 px-3 text-sm"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button
            onClick={handleSimulate}
            disabled={simulating || isDemoMode}
            className="btn-primary flex items-center gap-2 py-2 px-4 text-sm"
            title={isDemoMode ? 'Start backend to run simulation' : ''}
          >
            <Play size={13} className={simulating ? 'animate-pulse' : ''} />
            {simulating ? 'Running…' : 'Run Simulation'}
          </button>
        </div>
      </div>

      {/* Info banners */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex items-start gap-2.5 bg-white/[0.03] border border-white/[0.06] rounded-xl p-3 text-xs text-slate-500">
          <Info size={13} className="text-cyan/70 flex-shrink-0 mt-0.5" />
          <span>
            <strong className="text-slate-400">Test Set Replay:</strong>{' '}
            Simulation replays real ULB dataset rows — not live bank traffic.
            The <span className="text-amber-400 font-medium">Ground Truth</span> column shows actual fraud labels.
          </span>
        </div>
        <div className="flex items-start gap-2.5 bg-cyan/[0.04] border border-cyan/[0.12] rounded-xl p-3 text-xs text-slate-500">
          <Brain size={13} className="text-cyan/70 flex-shrink-0 mt-0.5" />
          <span>
            <strong className="text-cyan/90">Explainable AI:</strong>{' '}
            Hover any row for SHAP feature contributions — top drivers behind each fraud score.
          </span>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-500/8 border border-red-500/20 rounded-xl p-4 text-sm text-red-400">
          <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
          <div>{error}</div>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Scored" value={stats.total} icon={<Activity size={17} />} colorClass="text-cyan" />
        <StatCard label="Auto-Blocked" value={stats.block} icon={<ShieldX size={17} />} colorClass="text-red-400" subtitle="Score > 0.85" />
        <StatCard label="Under Review" value={stats.review} icon={<Eye size={17} />} colorClass="text-amber-400"
          subtitle={stats.pending_review > 0 ? `${stats.pending_review} pending decision` : 'Score 0.50–0.85'} />
        <StatCard label="Auto-Approved" value={stats.approve} icon={<CheckCircle size={17} />} colorClass="text-emerald-400" subtitle="Score < 0.50" />
      </div>

      {/* Demo mode fraud injection disclaimer */}
      {stats.total > 0 && (
        <div className="flex items-start gap-2.5 bg-amber-500/[0.06] border border-amber-500/20 rounded-xl p-3 text-xs text-slate-400">
          <AlertTriangle size={13} className="text-amber-400/80 flex-shrink-0 mt-0.5" />
          <span>
            <strong className="text-amber-400">Why is the block/reject rate high?</strong>
            {' '}Simulation demo mode intentionally injects{' '}
            <strong className="text-white">35% fraud cases</strong> for showcase visibility.
            The real ULB dataset has only <strong className="text-white">~0.17% fraud</strong>.
            {stats.total > 0 && stats.block + stats.review > 0 && (
              <span className="text-slate-500">
                {' '}Current flagged ratio: {(((stats.block + stats.review) / stats.total) * 100).toFixed(1)}%
                (demo) vs ~0.17% in production.
              </span>
            )}
          </span>
        </div>
      )}

      {/* Filter tabs — Tier */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-slate-600 text-xs font-medium">TIER</span>
        {(['', 'BLOCK', 'REVIEW', 'APPROVE'] as const).map((tier) => (
          <button
            key={tier}
            onClick={() => setFilterTier(tier)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ${
              filterTier === tier
                ? tier === 'BLOCK'
                  ? 'bg-red-500/15 text-red-400 border border-red-500/30'
                  : tier === 'REVIEW'
                  ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                  : tier === 'APPROVE'
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                  : 'bg-white/10 text-white border border-white/15'
                : 'bg-white/[0.03] text-slate-600 border border-white/[0.06] hover:text-slate-300 hover:bg-white/[0.06]'
            }`}
          >
            {tier || 'ALL'}
          </button>
        ))}

        <span className="ml-4 text-slate-600 text-xs font-medium">SOURCE</span>
        {([['', 'All'], ['simulation', 'Simulation'], ['live', 'Live'], ['imported', 'Imported']] as [SourceFilter, string][]).map(([src, label]) => (
          <button
            key={src}
            onClick={() => { setFilterSource(src); if (src !== 'imported') setFilterBatchId(null) }}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ${
              filterSource === src
                ? src === 'imported'
                  ? 'bg-cyan/15 text-cyan border border-cyan/30'
                  : src === 'simulation'
                  ? 'bg-blue-500/15 text-blue-400 border border-blue-500/30'
                  : src === 'live'
                  ? 'bg-purple-500/15 text-purple-400 border border-purple-500/30'
                  : 'bg-white/10 text-white border border-white/15'
                : 'bg-white/[0.03] text-slate-600 border border-white/[0.06] hover:text-slate-300 hover:bg-white/[0.06]'
            }`}
          >
            {label}
          </button>
        ))}

        {filterBatchId && (
          <span className="ml-2 flex items-center gap-1.5 text-xs text-cyan bg-cyan/10 border border-cyan/25 px-2.5 py-1 rounded-lg">
            Batch #{filterBatchId}
            <button onClick={() => setFilterBatchId(null)} className="hover:text-white transition-colors">×</button>
          </span>
        )}

        <span className="ml-auto flex items-center gap-1 text-xs text-slate-600">
          <Brain size={11} className="text-cyan/60" />
          Hover row for SHAP
        </span>
      </div>

      {/* Table */}
      <div className="glass-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Transaction</th>
                <th>User</th>
                <th>Amount</th>
                <th>Fused Score</th>
                <th>XGB</th>
                <th>IF</th>
                <th>Decision</th>
                <th className="flex items-center gap-1"><Brain size={11} className="text-cyan/60" />Top Driver</th>
                <th>Ground Truth</th>
                <th>Type</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {transactions.length === 0 && !loading && (
                <tr>
                  <td colSpan={11} className="text-center py-16">
                    <div className="flex flex-col items-center gap-4">
                      <div className="w-16 h-16 rounded-2xl bg-cyan/5 border border-cyan/15 flex items-center justify-center">
                        <TrendingUp size={28} className="text-cyan/40" />
                      </div>
                      <div>
                        <div className="font-semibold text-sm" style={{ color: 'var(--text-secondary)' }}>No transactions yet</div>
                        <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>Click <strong className="text-cyan/80">Run Simulation</strong> to score test data from the ULB dataset</div>
                      </div>
                      {isDemoMode && (
                        <div className="text-xs px-3 py-1.5 rounded-lg" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                          💡 Backend offline — simulation disabled in demo mode
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              )}
              {loading && (
                <tr>
                  <td colSpan={11} className="text-center py-10">
                    <div className="flex items-center justify-center gap-2 text-slate-500">
                      <RefreshCw size={14} className="animate-spin text-cyan" />
                      Loading…
                    </div>
                  </td>
                </tr>
              )}
              {transactions.map((tx) => {
                const isHovered = hoveredId === tx.id
                const cached = getCached(tx.id)
                const topReason = getTopReason(tx.id)

                return (
                  <tr
                    key={tx.id}
                    className={`cursor-pointer transition-all duration-150 ${isHovered ? 'bg-white/[0.04]' : ''}`}
                    onClick={() => navigate(`/transaction/${tx.id}`)}
                    onMouseEnter={() => handleRowMouseEnter(tx)}
                    onMouseLeave={handleRowMouseLeave}
                  >
                    <td>
                      <span className="font-mono text-[11px] text-slate-500">
                        {tx.transaction_uuid?.slice(0, 8)}…
                      </span>
                    </td>
                    <td>
                      <span className="font-mono text-xs text-slate-400">{tx.synthetic_user_id}</span>
                    </td>
                    <td>
                      <span className="font-bold text-white">${tx.amount.toFixed(2)}</span>
                    </td>
                    <td className="min-w-[100px]">
                      {tx.final_score != null && (
                        <ScoreBar score={tx.final_score} tier={tx.decision_tier || 'APPROVE'} />
                      )}
                    </td>
                    <td>
                      <span className="font-mono text-xs text-slate-500">
                        {tx.xgb_score?.toFixed(3) ?? '—'}
                      </span>
                    </td>
                    <td>
                      <span className="font-mono text-xs text-slate-500">
                        {tx.if_score?.toFixed(3) ?? '—'}
                      </span>
                    </td>
                    <td>{tx.decision_tier && <TierBadge tier={tx.decision_tier} />}</td>

                    {/* SHAP top driver */}
                    <td>
                      {cached === 'loading' ? (
                        <span className="flex items-center gap-1 text-xs text-slate-600">
                          <RefreshCw size={9} className="animate-spin text-cyan/60" />
                          <span>analyzing…</span>
                        </span>
                      ) : topReason ? (
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                          topReason.isRisk
                            ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                            : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        }`}>
                          {topReason.isRisk ? '↑' : '↓'} {topReason.label}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-700 italic">hover to load</span>
                      )}
                    </td>

                    {/* Ground truth */}
                    <td><TruthBadge label={tx.true_label} /></td>

                    {/* Type / Source */}
                    <td>
                      {tx.import_batch_id != null ? (
                        <span
                          title={`CSV Import · Batch #${tx.import_batch_id}`}
                          className="text-xs text-cyan/80 bg-cyan/8 border border-cyan/15 px-2 py-0.5 rounded-full cursor-help"
                        >
                          Import
                        </span>
                      ) : tx.is_simulation ? (
                        <span className="text-xs text-blue-400/70 bg-blue-500/8 border border-blue-500/15 px-2 py-0.5 rounded-full">
                          Sim
                        </span>
                      ) : (
                        <span className="text-xs text-purple-400/70 bg-purple-500/8 border border-purple-500/15 px-2 py-0.5 rounded-full">
                          Live
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="text-xs text-slate-600">
                        {new Date(tx.created_at).toLocaleTimeString()}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* SHAP hover panel */}
        {hoveredId !== null && (() => {
          const cached = getCached(hoveredId)
          return (
            <div
              className="border-t border-cyan/10 bg-gradient-to-r from-cyan/[0.04] to-transparent px-6 py-4 animate-fade-in"
              onMouseEnter={() => setHoveredId(hoveredId)}
              onMouseLeave={handleRowMouseLeave}
            >
              <ShapTooltip
                features={Array.isArray(cached) ? cached : []}
                loading={cached === 'loading'}
                noData={cached === 'none'}
              />
            </div>
          )
        })()}
      </div>
    </div>
  )
}

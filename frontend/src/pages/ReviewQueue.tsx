// src/pages/ReviewQueue.tsx
import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ClipboardList, CheckCircle, XCircle, RefreshCw,
  ChevronDown, ChevronUp, Brain, Play, Clock,
  AlertTriangle, ArrowRight, TrendingUp, Shield, Zap,
} from 'lucide-react'
import { getReviewQueue, submitReviewDecision, runSimulation } from '../lib/api'
import { MOCK_REVIEW_QUEUE } from '../lib/mockData'
import type { ReviewQueueItem } from '../types'
import TierBadge from '../components/TierBadge'
import ScoreBar from '../components/ScoreBar'
import ShapChart from '../components/ShapChart'
import DecisionExplanation from '../components/DecisionExplanation'

type FilterKey = 'pending' | 'approved' | 'rejected' | 'all'

function timeInQueue(createdAt: string): string {
  const ms = Date.now() - new Date(createdAt).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

function getPriority(score: number): { label: string; cls: string; urgency: number } {
  if (score >= 0.80) return { label: 'CRITICAL', cls: 'priority-critical', urgency: 3 }
  if (score >= 0.65) return { label: 'HIGH',     cls: 'priority-high',     urgency: 2 }
  return               { label: 'MEDIUM',         cls: 'priority-medium',   urgency: 1 }
}

// ── Stats row ───────────────────────────────────────────────────
function QueueStats({ items }: { items: ReviewQueueItem[] }) {
  const pending = items.filter(i => i.status === 'pending')
  const avgScore = pending.length ? pending.reduce((s, i) => s + i.final_score, 0) / pending.length : 0
  const maxScore = pending.length ? Math.max(...pending.map(i => i.final_score)) : 0

  return (
    <div className="grid grid-cols-4 gap-3">
      {[
        { label: 'Pending Review', value: pending.length.toString(), icon: <Clock size={16} />, color: 'text-amber-400', bg: 'bg-amber-500/8 border-amber-500/15' },
        { label: 'Avg Risk Score', value: avgScore > 0 ? (avgScore * 100).toFixed(1) + '%' : '—', icon: <TrendingUp size={16} />, color: 'text-cyan', bg: 'bg-cyan/8 border-cyan/15' },
        { label: 'Highest Score', value: maxScore > 0 ? (maxScore * 100).toFixed(1) + '%' : '—', icon: <Shield size={16} />, color: 'text-red-400', bg: 'bg-red-500/8 border-red-500/15' },
        { label: 'Total Cases', value: items.length.toString(), icon: <ClipboardList size={16} />, color: 'text-slate-400', bg: 'bg-white/[0.03] border-white/[0.06]' },
      ].map(card => (
        <div key={card.label} className={`glass-card border p-4 flex items-center gap-3 ${card.bg}`}>
          <div className={card.color}>{card.icon}</div>
          <div>
            <div className={`text-xl font-extrabold ${card.color}`}>{card.value}</div>
            <div className="text-xs text-slate-600">{card.label}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function ReviewQueuePage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<ReviewQueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterKey>('pending')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState<number | null>(null)
  const [simulatingDemo, setSimulatingDemo] = useState(false)
  const [analystNote, setAnalystNote] = useState<Record<number, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [isDemoMode, setIsDemoMode] = useState(false)

  const fetchQueue = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getReviewQueue(filter)
      setItems(data)
      setIsDemoMode(false)
    } catch {
      setItems(filter === 'pending' || filter === 'all' ? MOCK_REVIEW_QUEUE : [])
      setIsDemoMode(true)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { fetchQueue() }, [fetchQueue])

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg)
    setTimeout(() => setSuccessMsg(null), 4000)
  }

  const handleDecision = async (item: ReviewQueueItem, decision: 'approved' | 'rejected') => {
    setSubmitting(item.id)
    try {
      await submitReviewDecision(item.id, { decision, analyst_note: analystNote[item.id] || undefined })
      setAnalystNote(prev => { const n = { ...prev }; delete n[item.id]; return n })
      setExpanded(null)
      showSuccess(
        decision === 'approved'
          ? `✓ Transaction #${item.transaction_id} approved as legitimate — logged.`
          : `✗ Transaction #${item.transaction_id} rejected — confirmed fraud.`
      )
      await fetchQueue()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to submit decision')
    } finally {
      setSubmitting(null)
    }
  }

  const handleRunDemo = async () => {
    setSimulatingDemo(true)
    setError(null)
    try {
      await runSimulation(20, 42)
      showSuccess('Simulation complete — REVIEW-tier transactions added to queue.')
      await fetchQueue()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Simulation failed — start the backend first.')
    } finally {
      setSimulatingDemo(false)
    }
  }

  const filterTabs: Array<{ key: FilterKey; label: string }> = [
    { key: 'pending',  label: 'Pending' },
    { key: 'approved', label: 'Approved' },
    { key: 'rejected', label: 'Rejected' },
    { key: 'all',      label: 'All' },
  ]
  const filterColors: Record<FilterKey, string> = {
    pending:  'text-amber-400 bg-amber-500/15 border-amber-500/25',
    approved: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/25',
    rejected: 'text-red-400 bg-red-500/15 border-red-500/25',
    all:      'text-slate-300 bg-white/10 border-white/15',
  }

  // Sort pending by priority (highest score first)
  const sortedItems = [...items].sort((a, b) => b.final_score - a.final_score)

  return (
    <div className="p-6 space-y-5 animate-fade-in">
      {/* Header */}
      <div className="section-header">
        <div>
          <h1 className="section-title">
            <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400"><ClipboardList size={18} /></div>
            Analyst Review Queue
          </h1>
          <p className="text-slate-600 text-sm mt-1.5">
            Transactions scoring 0.50–0.85 routed for analyst decision ·{' '}
            {isDemoMode && <span className="text-amber-500 font-medium">Demo Data</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRunDemo}
            disabled={simulatingDemo || isDemoMode}
            className="btn-ghost flex items-center gap-2 py-2 px-3 text-sm"
            title={isDemoMode ? 'Start backend to run simulation' : ''}
          >
            <Play size={13} className={simulatingDemo ? 'animate-pulse text-cyan' : ''} />
            {simulatingDemo ? 'Simulating…' : 'Run Simulation'}
          </button>
          <button onClick={fetchQueue} disabled={loading} className="btn-ghost flex items-center gap-2 py-2 px-3 text-sm">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats */}
      <QueueStats items={items} />

      {/* Why empty explanation */}
      <div className="flex items-start gap-3 bg-white/[0.03] border border-white/[0.06] rounded-xl p-3 text-xs text-slate-600">
        <Zap size={13} className="text-cyan/60 flex-shrink-0 mt-0.5" />
        <span>
          Items appear here only when a transaction scores <strong className="text-amber-400">0.50–0.85</strong> (REVIEW tier).
          BLOCK (&gt;0.85) and APPROVE (&lt;0.50) are automated — only borderline cases need human review.
          Run a simulation to populate the queue with realistic cases.
        </span>
      </div>

      {/* Toasts */}
      {error && (
        <div className="flex items-start gap-3 bg-red-500/8 border border-red-500/20 rounded-xl p-3 text-sm text-red-400">
          <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}
      {successMsg && (
        <div className="flex items-center gap-3 bg-emerald-500/8 border border-emerald-500/20 rounded-xl p-3 text-sm text-emerald-400 animate-fade-in">
          <CheckCircle size={15} />
          {successMsg}
        </div>
      )}

      {/* Filter tabs */}
      <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.06] rounded-xl p-1 w-fit">
        {filterTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 border ${
              filter === tab.key
                ? filterColors[tab.key]
                : 'text-slate-600 border-transparent hover:text-slate-300'
            }`}
          >
            {tab.label}
            {tab.key === 'pending' && items.filter(i => i.status === 'pending').length > 0 && (
              <span className="ml-1.5 bg-amber-500/20 text-amber-400 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                {items.filter(i => i.status === 'pending').length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Queue items */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-slate-600 gap-2">
          <RefreshCw size={15} className="animate-spin text-cyan" />
          Loading queue…
        </div>
      ) : sortedItems.length === 0 ? (
        <div className="glass-card p-14 text-center animate-fade-in">
          <div className="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto mb-4">
            <ClipboardList size={28} className="text-amber-500/60" />
          </div>
          <div className="text-lg font-semibold text-slate-300 mb-2">
            {filter === 'pending' ? 'Queue is Empty' : `No ${filter} cases`}
          </div>
          <div className="text-sm text-slate-600 max-w-sm mx-auto mb-6 leading-relaxed">
            {filter === 'pending'
              ? 'Transactions scoring 0.50–0.85 are routed here. Run a simulation to generate REVIEW-tier cases for the demo.'
              : `No ${filter} decisions recorded yet.`}
          </div>
          {filter === 'pending' && (
            <button
              onClick={handleRunDemo}
              disabled={simulatingDemo || isDemoMode}
              className="btn-primary inline-flex items-center gap-2 py-2.5 px-6 text-sm mx-auto"
            >
              <Play size={14} className={simulatingDemo ? 'animate-pulse' : ''} />
              {simulatingDemo ? 'Running…' : 'Run Fraud Simulation'}
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {sortedItems.map((item) => {
            const priority = getPriority(item.final_score)
            const isOpen = expanded === item.id
            const note = analystNote[item.id] || ''

            return (
              <div
                key={item.id}
                className={`glass-card border transition-all duration-200 overflow-hidden ${
                  isOpen
                    ? 'border-cyan/20 shadow-[0_0_30px_rgba(6,182,212,0.06)]'
                    : 'border-white/[0.06] hover:border-white/10'
                }`}
              >
                {/* Row header */}
                <div
                  className="flex items-center gap-4 p-4 cursor-pointer select-none"
                  onClick={() => setExpanded(isOpen ? null : item.id)}
                >
                  {/* Priority + score */}
                  <div className="flex flex-col items-center gap-1 w-16 flex-shrink-0">
                    <span className={priority.cls}>{priority.label}</span>
                    <span className="font-mono text-xs font-bold text-white">{(item.final_score * 100).toFixed(1)}%</span>
                  </div>

                  {/* Divider */}
                  <div className="w-px h-10 bg-white/5 flex-shrink-0" />

                  {/* Main info */}
                  <div className="flex-1 grid grid-cols-6 gap-4 items-center min-w-0">
                    {/* ID + User */}
                    <div className="col-span-2">
                      <div className="font-mono text-xs text-slate-500 truncate">{item.transaction_uuid.slice(0, 8)}…</div>
                      <div className="font-mono text-xs text-slate-400 font-medium mt-0.5 truncate">{item.synthetic_user_id}</div>
                    </div>

                    {/* Amount */}
                    <div>
                      <div className="text-xs text-slate-600 mb-0.5">Amount</div>
                      <div className="font-bold text-white">${item.amount.toFixed(2)}</div>
                    </div>

                    {/* Score bar */}
                    <div>
                      <div className="text-xs text-slate-600 mb-1">Risk Score</div>
                      <ScoreBar score={item.final_score} tier="REVIEW" />
                      <div className="text-[10px] text-slate-600 mt-0.5">
                        XGB {item.xgb_score.toFixed(3)} · IF {item.if_score.toFixed(3)}
                      </div>
                    </div>

                    {/* Status */}
                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${
                        item.status === 'pending'
                          ? 'bg-amber-500/10 text-amber-400 border-amber-500/25'
                          : item.status === 'approved'
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25'
                          : 'bg-red-500/10 text-red-400 border-red-500/25'
                      }`}>
                        {item.status.toUpperCase()}
                      </span>
                    </div>

                    {/* Time + actions */}
                    <div className="flex items-center justify-end gap-3">
                      <div className="text-xs text-slate-600 flex items-center gap-1">
                        <Clock size={10} />{timeInQueue(item.created_at)}
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); navigate(`/transaction/${item.transaction_id}`) }}
                        className="text-xs text-cyan/70 hover:text-cyan transition-colors flex items-center gap-1"
                      >
                        Detail <ArrowRight size={10} />
                      </button>
                      {isOpen ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
                    </div>
                  </div>
                </div>

                {/* Quick approve/reject (always visible for pending) */}
                {item.status === 'pending' && !isOpen && (
                  <div className="flex items-center gap-2 px-4 pb-3">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDecision(item, 'approved') }}
                      disabled={submitting === item.id}
                      className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg
                                 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20
                                 hover:bg-emerald-500/20 transition-all duration-150 active:scale-95"
                    >
                      <CheckCircle size={12} />
                      {submitting === item.id ? '…' : 'Approve'}
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDecision(item, 'rejected') }}
                      disabled={submitting === item.id}
                      className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg
                                 bg-red-500/10 text-red-400 border border-red-500/20
                                 hover:bg-red-500/20 transition-all duration-150 active:scale-95"
                    >
                      <XCircle size={12} />
                      {submitting === item.id ? '…' : 'Reject'}
                    </button>
                    <span className="text-[11px] text-slate-700">Quick action — or expand for SHAP</span>
                  </div>
                )}

                {/* Expanded panel */}
                {isOpen && (
                  <div className="border-t border-white/5 p-5 space-y-5 animate-slide-up">
                    {/* SHAP chart */}
                    {item.shap_explanations?.length > 0 && (
                      <div>
                        <div className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                          <Brain size={14} className="text-cyan" />
                          SHAP Feature Contributions
                          <span className="text-xs text-slate-600 font-normal ml-1">(XGBoost native SHAP)</span>
                        </div>
                        <ShapChart features={item.shap_explanations} />
                      </div>
                    )}

                    {/* AI Decision Explanation */}
                    <DecisionExplanation
                      decisionTier="REVIEW"
                      finalScore={item.final_score}
                      xgbScore={item.xgb_score}
                      ifScore={item.if_score}
                      amount={item.amount}
                      shapFeatures={item.shap_explanations || []}
                    />

                    {/* Decision area */}
                    {item.status === 'pending' && (
                      <div className="space-y-3 border-t border-white/5 pt-4">
                        <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Analyst Decision</div>
                        <div>
                          <label className="text-xs text-slate-600 mb-1.5 block">Investigation note (optional)</label>
                          <textarea
                            value={note}
                            onChange={(e) => setAnalystNote(prev => ({ ...prev, [item.id]: e.target.value }))}
                            className="form-input w-full h-20 resize-none text-sm"
                            placeholder="Add reasoning for your decision…"
                          />
                        </div>
                        <div className="flex items-center gap-3">
                          <button
                            onClick={() => handleDecision(item, 'approved')}
                            disabled={submitting === item.id}
                            className="btn-success flex items-center gap-2 text-sm py-2 px-5"
                          >
                            <CheckCircle size={14} />
                            {submitting === item.id ? 'Submitting…' : 'Approve — Legitimate'}
                          </button>
                          <button
                            onClick={() => handleDecision(item, 'rejected')}
                            disabled={submitting === item.id}
                            className="btn-danger flex items-center gap-2 text-sm py-2 px-5"
                          >
                            <XCircle size={14} />
                            Reject — Confirm Fraud
                          </button>
                          <span className="text-xs text-slate-600">Decision is final and timestamped</span>
                        </div>
                      </div>
                    )}

                    {/* Decision result */}
                    {item.status !== 'pending' && (
                      <div className={`flex items-center gap-3 pt-4 border-t border-white/5 text-sm font-semibold ${
                        item.status === 'approved' ? 'text-emerald-400' : 'text-red-400'
                      }`}>
                        {item.status === 'approved' ? <CheckCircle size={16} /> : <XCircle size={16} />}
                        <span>
                          {item.status === 'approved' ? 'Approved as legitimate' : 'Rejected — confirmed fraud'}
                        </span>
                        {item.reviewed_at && (
                          <span className="text-slate-600 font-normal text-xs">
                            at {new Date(item.reviewed_at).toLocaleString()}
                          </span>
                        )}
                        {item.analyst_note && (
                          <span className="text-slate-500 font-normal text-xs italic ml-2">"{item.analyst_note}"</span>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

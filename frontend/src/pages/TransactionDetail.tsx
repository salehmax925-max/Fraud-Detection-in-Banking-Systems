// src/pages/TransactionDetail.tsx
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, FileSearch, Cpu, Zap, Brain, RefreshCw,
  CheckCircle, XCircle, AlertTriangle, Info,
} from 'lucide-react'
import { getTransaction } from '../lib/api'
import { MOCK_TRANSACTIONS, getShapForTx } from '../lib/mockData'
import type { TransactionDetail as TxDetail } from '../types'
import TierBadge from '../components/TierBadge'
import ScoreBar from '../components/ScoreBar'
import ShapChart from '../components/ShapChart'
import DecisionExplanation from '../components/DecisionExplanation'

// ── Ground truth panel ──────────────────────────────────────────
function GroundTruthPanel({ tx }: { tx: TxDetail }) {
  if (!tx.is_simulation) return null

  const isKnown = (tx as any).true_label !== null && (tx as any).true_label !== undefined
  const isFraud = (tx as any).true_label === 1
  const tier = tx.decision_tier || 'APPROVE'
  const modelSaidFraud = tier === 'BLOCK' || tier === 'REVIEW'

  const correct = isKnown
    ? ((isFraud && modelSaidFraud) || (!isFraud && !modelSaidFraud))
    : null

  return (
    <div className={`glass-card border p-5 ${
      !isKnown ? 'border-white/[0.06]' :
      correct ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-red-500/20 bg-red-500/5'
    }`}>
      <div className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Info size={14} className="text-cyan" />
        Ground Truth (ULB Dataset)
        <span className="text-xs text-slate-600 font-normal">— simulation rows only</span>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <div className="text-xs text-slate-600 mb-1">Actual Label</div>
          {isKnown ? (
            isFraud
              ? <span className="badge-fraud text-sm">● FRAUD (Class=1)</span>
              : <span className="badge-legit text-sm">● LEGITIMATE (Class=0)</span>
          ) : (
            <span className="text-slate-600 text-sm">Unknown</span>
          )}
        </div>
        <div>
          <div className="text-xs text-slate-600 mb-1">Model Decision</div>
          <TierBadge tier={tier} />
        </div>
        <div>
          <div className="text-xs text-slate-600 mb-1">Outcome</div>
          {isKnown ? (
            correct
              ? (
                <span className="flex items-center gap-1 text-emerald-400 text-sm font-semibold">
                  <CheckCircle size={14} />
                  {isFraud ? 'Correct — fraud caught' : 'Correct — legit approved'}
                </span>
              )
              : (
                <span className="flex items-center gap-1 text-red-400 text-sm font-semibold">
                  <XCircle size={14} />
                  {isFraud ? 'Missed — fraud escaped' : 'False positive — legit flagged'}
                </span>
              )
          ) : <span className="text-slate-600 text-sm">—</span>}
        </div>
      </div>
    </div>
  )
}

export default function TransactionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [tx, setTx] = useState<TxDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    getTransaction(Number(id))
      .then(data => {
        // If no SHAP and it's a known ID, inject mock SHAP for demo
        if (!data.shap_explanations?.length) {
          data.shap_explanations = getShapForTx(Number(id))
        }
        setTx(data)
      })
      .catch(() => {
        // Fallback to mock data
        const mock = MOCK_TRANSACTIONS.find(t => t.id === Number(id))
        if (mock) {
          setTx({
            ...mock,
            v_features: { V1: -1.36, V2: -0.07, V3: 2.54, V4: 1.38, V5: -0.34, V6: 0.46, V7: 0.24, V8: 0.10,
                          V9: 0.36, V10: 0.09, V11: -0.55, V12: -0.62, V13: -0.99, V14: -0.31, V15: 1.47, V16: -0.47,
                          V17: 0.21, V18: 0.03, V19: 0.40, V20: 0.25, V21: -0.02, V22: 0.28, V23: 0.11, V24: 0.07,
                          V25: 0.13, V26: -0.19, V27: 0.13, V28: -0.02 },
            tx_freq_1h: 2,
            tx_freq_24h: 7,
            amount_deviation_z: 1.43,
            time_of_day_risk: 0,
            velocity_change: 0.62,
            location_entropy: 0,
            shap_explanations: getShapForTx(Number(id)),
            review_status: null,
          } as any)
        } else {
          setError('Transaction not found. Start the backend to load real data.')
        }
      })
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-3 text-slate-600">
          <RefreshCw size={18} className="animate-spin text-cyan" />
          Loading transaction…
        </div>
      </div>
    )
  }

  if (error || !tx) {
    return (
      <div className="p-6">
        <div className="flex items-start gap-3 bg-red-500/8 border border-red-500/20 rounded-xl p-4 text-red-400">
          <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
          {error || 'Transaction not found'}
        </div>
        <button onClick={() => navigate(-1)} className="btn-ghost mt-4 flex items-center gap-2 text-sm py-2 px-4">
          <ArrowLeft size={13} /> Back
        </button>
      </div>
    )
  }

  const tier = tx.decision_tier || 'APPROVE'
  const tierBorderColor = {
    BLOCK:   'border-red-500/20 bg-red-500/5',
    REVIEW:  'border-amber-500/20 bg-amber-500/5',
    APPROVE: 'border-emerald-500/20 bg-emerald-500/5',
  }[tier] || 'border-white/[0.06]'

  const behavioralFeatures = [
    { label: 'Tx Frequency (1h)',   value: tx.tx_freq_1h,                 desc: 'Transactions in last 1 hour (causal window)' },
    { label: 'Tx Frequency (24h)',  value: tx.tx_freq_24h,                desc: 'Transactions in last 24 hours (causal window)' },
    { label: 'Amount Deviation Z',  value: tx.amount_deviation_z?.toFixed(3), desc: 'Standard deviations from user mean amount' },
    { label: 'Night-time Risk',     value: tx.time_of_day_risk === 1 ? '1 — Night (00–05h)' : '0 — Normal hours', desc: 'Binary flag: midnight to 5am' },
    { label: 'Velocity Change',     value: tx.velocity_change?.toFixed(4), desc: 'Amount rate change (last 3 transactions)' },
    { label: 'New Device/Region',   value: tx.location_entropy === 1 ? '1 — New marker' : '0 — Known marker', desc: 'Binary flag: first-seen device hash' },
  ]

  return (
    <div className="p-6 space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => navigate(-1)} className="btn-ghost flex items-center gap-2 text-sm py-2 px-3">
          <ArrowLeft size={13} /> Back
        </button>
        <div className="flex-1">
          <h1 className="section-title">
            <div className="p-2 rounded-xl bg-cyan/10 text-cyan"><FileSearch size={18} /></div>
            Transaction Detail
          </h1>
          <div className="flex items-center gap-3 mt-1.5">
            <span className="font-mono text-xs text-slate-600">{tx.transaction_uuid}</span>
            {tx.is_simulation && (
              <span className="text-xs text-blue-400/70 bg-blue-500/8 border border-blue-500/15 px-2 py-0.5 rounded-full">
                Test Set Replay
              </span>
            )}
            {tx.review_status && tx.review_status !== 'pending' && (
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${
                tx.review_status === 'approved'
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-red-500/10 text-red-400 border-red-500/20'
              }`}>
                {tx.review_status === 'approved' ? '✓ Analyst Approved' : '✗ Analyst Rejected'}
              </span>
            )}
          </div>
        </div>
        <TierBadge tier={tier} large />
      </div>

      {/* Ground truth (simulation rows) */}
      <GroundTruthPanel tx={tx} />

      {/* Decision hero */}
      <div className={`glass-card border ${tierBorderColor} p-6`}>
        <div className="grid grid-cols-4 gap-6">
          <div>
            <div className="text-xs text-slate-600 mb-1.5">User (Synthetic)</div>
            <div className="font-mono text-sm text-white font-medium">{tx.synthetic_user_id}</div>
            <div className="text-[10px] text-slate-700 mt-1">hash-bucketed Time+Amount proxy</div>
          </div>
          <div>
            <div className="text-xs text-slate-600 mb-1.5">Amount</div>
            <div className="text-2xl font-extrabold text-white">${tx.amount.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-600 mb-2">Fused Score (0.70×XGB + 0.30×IF)</div>
            <ScoreBar score={tx.final_score || 0} tier={tier} />
            <div className="font-mono text-xl font-extrabold text-white mt-1.5">{tx.final_score?.toFixed(4)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-600 mb-1.5">Decision</div>
            <TierBadge tier={tier} large />
            <div className="text-xs text-slate-600 mt-1.5">
              {tier === 'BLOCK' ? 'Score > 0.85 — Auto-blocked'
                : tier === 'REVIEW' ? 'Score 0.50–0.85 — Analyst review'
                : 'Score < 0.50 — Auto-approved'}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-5">
        {/* Score Breakdown */}
        <div className="glass-card p-5">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Cpu size={14} className="text-cyan" /> Score Breakdown
          </h2>
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-xs text-slate-500 mb-1.5">
                <span>XGBoost P(fraud) × <strong className="text-white">0.70</strong> weight</span>
                <span className="font-mono text-white">{tx.xgb_score?.toFixed(4)}</span>
              </div>
              <div className="score-bar">
                <div className="score-bar-fill bg-cyan/70" style={{ width: `${(tx.xgb_score || 0) * 100}%` }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between text-xs text-slate-500 mb-1.5">
                <span>Isolation Forest score × <strong className="text-white">0.30</strong> weight</span>
                <span className="font-mono text-white">{tx.if_score?.toFixed(4)}</span>
              </div>
              <div className="score-bar">
                <div className="score-bar-fill bg-purple/70" style={{ width: `${(tx.if_score || 0) * 100}%` }} />
              </div>
            </div>
            <div className="pt-3 border-t border-white/5">
              <div className="flex justify-between text-xs font-semibold mb-2">
                <span className="text-white">Fused Score</span>
                <span className="font-mono text-white">{tx.final_score?.toFixed(4)}</span>
              </div>
              <ScoreBar score={tx.final_score || 0} tier={tier} />
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-white/5 text-xs text-slate-700">
            Thresholds: BLOCK &gt;0.85 | REVIEW ≥0.50 | APPROVE &lt;0.50
          </div>
        </div>

        {/* Behavioral Features */}
        <div className="glass-card p-5">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Zap size={14} className="text-cyan" /> Behavioral Features
            <span className="text-xs text-slate-600 font-normal">Digital Twin Engine</span>
          </h2>
          <div className="space-y-3.5">
            {behavioralFeatures.map((f) => (
              <div key={f.label} className="flex items-start justify-between">
                <div>
                  <div className="text-sm text-slate-300">{f.label}</div>
                  <div className="text-xs text-slate-600">{f.desc}</div>
                </div>
                <div className="font-mono text-sm font-bold text-white ml-3 flex-shrink-0">
                  {f.value ?? '—'}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* SHAP Explanation */}
      <div className="glass-card p-5">
        <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Brain size={14} className="text-cyan" />
          SHAP Feature Importance
          <span className="text-xs text-slate-600 font-normal ml-1">
            {tx.shap_explanations?.length
              ? `Top ${tx.shap_explanations.length} features · XGBoost native SHAP`
              : '(no SHAP data — run a simulation to generate scored transactions)'}
          </span>
        </h2>
        {tx.shap_explanations?.length > 0 ? (
          <>
            <ShapChart features={tx.shap_explanations} />
            <div className="mt-3 pt-3 border-t border-white/5 text-xs text-slate-700">
              <span className="text-red-400/80">↑ Red bars</span> = features pushing score toward fraud ·{' '}
              <span className="text-emerald-400/80">↓ Green bars</span> = features pulling score toward legitimate.
              SHAP values are additive: sum equals the model's log-odds output.
            </div>
          </>
        ) : (
          <div className="flex items-center gap-3 text-slate-600 text-sm p-4 bg-white/[0.02] rounded-xl">
            <AlertTriangle size={14} className="text-amber-500/60" />
            No SHAP data stored for this transaction yet. New transactions include SHAP automatically.
          </div>
        )}
      </div>

      {/* AI Decision Explanation */}
      <div className="glass-card p-5">
        <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Brain size={14} className="text-cyan" />
          AI Decision Explanation
          <span className="text-xs text-slate-600 font-normal ml-1">— Ollama qwen3:8b · click to generate</span>
        </h2>
        <DecisionExplanation
          decisionTier={tx.decision_tier || 'APPROVE'}
          finalScore={tx.final_score || 0}
          xgbScore={tx.xgb_score ?? undefined}
          ifScore={tx.if_score ?? undefined}
          amount={tx.amount}
          shapFeatures={tx.shap_explanations || []}
          behavioral={{
            tx_freq_1h: tx.tx_freq_1h ?? null,
            tx_freq_24h: tx.tx_freq_24h ?? null,
            amount_deviation_z: tx.amount_deviation_z ?? null,
            time_of_day_risk: tx.time_of_day_risk ?? null,
            velocity_change: tx.velocity_change ?? null,
            location_entropy: tx.location_entropy ?? null,
          }}
        />
      </div>

      {/* PCA features */}
      <div className="glass-card p-5">
        <h2 className="text-sm font-semibold text-white mb-4">PCA Features (V1–V28)</h2>
        <div className="grid grid-cols-7 gap-1.5">
          {Object.entries(tx.v_features || {})
            .sort(([a], [b]) => parseInt(a.slice(1)) - parseInt(b.slice(1)))
            .map(([key, val]) => (
              <div key={key} className="bg-white/[0.03] border border-white/5 rounded-xl px-2 py-2 text-center hover:border-cyan/20 transition-colors">
                <div className="text-[10px] text-slate-600 font-medium">{key}</div>
                <div className="font-mono text-xs text-slate-400 mt-0.5">{Number(val).toFixed(3)}</div>
              </div>
            ))
          }
        </div>
        <div className="mt-3 text-xs text-slate-700">
          V1–V28 are PCA-anonymized by ULB dataset providers. Left unchanged by the StandardScaler (only Amount and Time are scaled).
        </div>
      </div>
    </div>
  )
}

// src/pages/ModelPerformance.tsx
// Premium 6-panel model performance dashboard
// All metrics from evaluation_report.json — nothing hardcoded.
import { useState, useEffect } from 'react'
import {
  BarChart2, RefreshCw, TrendingUp, Target, Award,
  AlertCircle, Info, ChevronDown, ChevronUp, Zap,
} from 'lucide-react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine, Cell, AreaChart, Area,
} from 'recharts'
import { getMetrics } from '../lib/api'
import { MOCK_METRICS } from '../lib/mockData'
import type { MetricsResponse, ModelMetrics } from '../types'

// ── Animated metric card ────────────────────────────────────────
function MetricCard({
  label, value, pct, color, hint, highlight = false,
}: {
  label: string; value: string | number; pct?: number; color: string
  hint?: string; highlight?: boolean
}) {
  return (
    <div className={`glass-card p-5 flex flex-col gap-3 transition-all duration-300
      ${highlight ? 'border-cyan/20 hover:border-cyan/30 shadow-[0_0_30px_rgba(6,182,212,0.06)]' : 'border-white/[0.06] hover:border-white/10'}`}>
      <div className="text-xs text-slate-600 font-medium uppercase tracking-wider">{label}</div>
      {pct !== undefined && (
        <div className="relative h-1.5 bg-white/5 rounded-full overflow-hidden">
          <div
            className={`absolute left-0 top-0 h-full rounded-full transition-all duration-1000 ease-out ${color}`}
            style={{ width: `${pct * 100}%` }}
          />
        </div>
      )}
      <div className={`text-3xl font-extrabold font-mono tracking-tight ${highlight ? 'text-gradient-cyan' : 'text-white'}`}>
        {typeof value === 'number' ? value.toFixed(4) : value}
      </div>
      {hint && <div className="text-xs text-slate-700 leading-relaxed">{hint}</div>}
    </div>
  )
}

// ── Confusion matrix ────────────────────────────────────────────
function ConfusionMatrix({ cm }: { cm: ModelMetrics['confusion_matrix'] }) {
  const total = cm.true_negatives + cm.false_positives + cm.false_negatives + cm.true_positives
  const cells = [
    { label: 'True Negative', value: cm.true_negatives, desc: 'Legit → APPROVE', color: 'text-emerald-400', border: 'border-emerald-500/20', bg: 'bg-emerald-500/5' },
    { label: 'False Positive', value: cm.false_positives, desc: 'Legit → Flagged', color: 'text-amber-400', border: 'border-amber-500/20', bg: 'bg-amber-500/5' },
    { label: 'False Negative', value: cm.false_negatives, desc: 'Fraud → Missed', color: 'text-red-400', border: 'border-red-500/20', bg: 'bg-red-500/5' },
    { label: 'True Positive', value: cm.true_positives, desc: 'Fraud → Caught', color: 'text-emerald-400', border: 'border-emerald-500/20', bg: 'bg-emerald-500/5' },
  ]
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {cells.map(({ label, value, desc, color, border, bg }) => (
          <div key={label} className={`${bg} border ${border} rounded-xl p-4 text-center`}>
            <div className={`text-2xl font-extrabold font-mono ${color}`}>{value.toLocaleString()}</div>
            <div className="text-xs font-semibold text-slate-400 mt-1">{label}</div>
            <div className="text-[10px] text-slate-600 mt-0.5">{desc}</div>
            <div className="text-[10px] text-slate-700 mt-1">{((value / total) * 100).toFixed(3)}%</div>
          </div>
        ))}
      </div>
      <div className="text-xs text-slate-700 text-center leading-relaxed">
        Predicted Negative ← | → Predicted Positive (rows = actual labels)
      </div>
    </div>
  )
}

// ── Metric explanation accordion ────────────────────────────────
const METRIC_EXPLANATIONS = [
  { label: 'Precision', formula: 'TP / (TP + FP)', meaning: 'Of all transactions flagged as fraud, what fraction were actually fraud? High precision = few false alarms.' },
  { label: 'Recall (Sensitivity)', formula: 'TP / (TP + FN)', meaning: 'Of all actual fraud cases, what fraction did we catch? High recall = fewer missed frauds.' },
  { label: 'F1-Score', formula: '2 × (P × R) / (P + R)', meaning: 'Harmonic mean of precision and recall. Balanced metric for imbalanced datasets.' },
  { label: 'ROC-AUC', formula: 'Area under ROC curve', meaning: 'Probability that the model ranks a random fraud higher than a random legitimate transaction. AUC=1.0 is perfect.' },
  { label: 'MCC (Matthews)', formula: '(TP×TN − FP×FN) / √(...)', meaning: 'Most reliable single metric for severely imbalanced classes (0.17% fraud). Accounts for all 4 confusion matrix cells.' },
]

function MetricExplanations() {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="glass-card p-5 space-y-2">
      <div className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <Info size={14} className="text-cyan" />
        Metric Explanations (Committee Defense Reference)
      </div>
      {METRIC_EXPLANATIONS.map(({ label, formula, meaning }) => (
        <div key={label} className="border border-white/5 rounded-xl overflow-hidden">
          <button
            onClick={() => setOpen(open === label ? null : label)}
            className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-300 hover:text-white hover:bg-white/[0.02] transition-colors"
          >
            <span className="font-medium">{label}</span>
            <div className="flex items-center gap-3">
              <code className="font-mono text-xs text-cyan/70 hidden sm:block">{formula}</code>
              {open === label ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
            </div>
          </button>
          {open === label && (
            <div className="px-4 pb-4 text-xs text-slate-500 border-t border-white/5 pt-3 animate-fade-in leading-relaxed">
              {meaning}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default function ModelPerformancePage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [isDemoMode, setIsDemoMode] = useState(false)

  const fetchMetrics = async () => {
    setLoading(true)
    try {
      const data = await getMetrics()
      setMetrics(data)
      setIsDemoMode(false)
    } catch {
      setMetrics(MOCK_METRICS)
      setIsDemoMode(true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchMetrics() }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-3 text-slate-600">
          <RefreshCw size={18} className="animate-spin text-cyan" />
          Loading evaluation metrics…
        </div>
      </div>
    )
  }

  if (!metrics) return null

  const { model_comparison, primary_metrics, roc_curve_data, precision_recall_curve_data } = metrics
  const hybrid = model_comparison.hybrid_fusion as ModelMetrics
  const xgb    = model_comparison.xgboost_only as ModelMetrics
  const ifo    = model_comparison.isolation_forest_only as ModelMetrics

  // Comparison bar data
  const compData = [
    { metric: 'Precision', Hybrid: hybrid.precision, XGBoost: xgb.precision, IF: ifo.precision },
    { metric: 'Recall',    Hybrid: hybrid.recall,    XGBoost: xgb.recall,    IF: ifo.recall },
    { metric: 'F1',        Hybrid: hybrid.f1_score,  XGBoost: xgb.f1_score,  IF: ifo.f1_score },
    { metric: 'ROC-AUC',   Hybrid: hybrid.roc_auc,   XGBoost: xgb.roc_auc,  IF: ifo.roc_auc },
    { metric: 'MCC',       Hybrid: hybrid.mcc,        XGBoost: xgb.mcc,      IF: ifo.mcc },
  ]

  // ROC curve (sampled)
  const sampleRoc = (fpr: number[], tpr: number[], n = 200) => {
    const step = Math.max(1, Math.floor(fpr.length / n))
    return fpr.filter((_, i) => i % step === 0)
              .map((f, i) => ({ fpr: f, tpr: tpr[i * step] || 0 }))
  }
  const rocH = sampleRoc(roc_curve_data.hybrid.fpr, roc_curve_data.hybrid.tpr)
  const rocX = sampleRoc(roc_curve_data.xgb.fpr,    roc_curve_data.xgb.tpr)
  const rocI = sampleRoc(roc_curve_data.if.fpr,     roc_curve_data.if.tpr)
  const rocData = rocH.map((pt, i) => ({
    fpr: pt.fpr,
    Hybrid:  pt.tpr,
    XGBoost: rocX[i]?.tpr ?? 0,
    IF:      rocI[i]?.tpr ?? 0,
  }))

  // Precision-Recall curve
  const prData = (precision_recall_curve_data.recall || []).map((r, i) => ({
    recall: r,
    precision: precision_recall_curve_data.precision[i] ?? 0,
  }))

  // Tier breakdown donut data (derived from confusion matrix)
  const cm = hybrid.confusion_matrix
  const tierData = [
    { name: 'True Positive', value: cm.true_positives,  fill: '#10b981' },
    { name: 'False Positive', value: cm.false_positives, fill: '#f59e0b' },
    { name: 'False Negative', value: cm.false_negatives, fill: '#ef4444' },
  ]

  const TOOLTIP_STYLE = {
    contentStyle: { background: '#0d1526', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, fontSize: 12 },
    labelStyle: { color: '#64748b' },
  }

  return (
    <div className="p-6 space-y-5 animate-fade-in">
      {/* Header */}
      <div className="section-header">
        <div>
          <h1 className="section-title">
            <div className="p-2 rounded-xl bg-cyan/10 text-cyan"><BarChart2 size={18} /></div>
            Model Performance
            <span className="text-xs font-normal text-slate-600 ml-1">Thesis Table 7</span>
          </h1>
          <p className="text-slate-600 text-sm mt-1.5">
            All metrics from real held-out test set · {metrics.test_set_size.toLocaleString()} rows ·{' '}
            {metrics.test_fraud_count} fraud ({metrics.test_fraud_pct.toFixed(4)}%) ·{' '}
            {isDemoMode && <span className="text-amber-500 font-medium">Demo Data</span>}
          </p>
        </div>
        <button onClick={fetchMetrics} disabled={loading} className="btn-ghost flex items-center gap-2 py-2 px-3 text-sm">
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {isDemoMode && (
        <div className="flex items-start gap-3 bg-amber-500/8 border border-amber-500/15 rounded-xl p-3 text-xs text-amber-500/80">
          <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
          Demo data shown. Start backend + complete Colab training to see real evaluation_report.json metrics.
        </div>
      )}

      {/* Primary metric pills — Hybrid Fusion */}
      <div className="glass-card p-5 border border-cyan/15">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Award size={15} className="text-cyan" />
            Hybrid Fusion — Primary Metrics
            <span className="text-xs text-slate-600 font-normal">(threshold = {metrics.decision_thresholds.review})</span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-cyan/70">
            <Zap size={11} />
            XGBoost (0.70) + Isolation Forest (0.30)
          </div>
        </div>
        <div className="grid grid-cols-5 gap-3">
          <MetricCard label="Precision"  value={hybrid.precision}  pct={hybrid.precision}  color="bg-cyan" highlight />
          <MetricCard label="Recall"     value={hybrid.recall}     pct={hybrid.recall}     color="bg-cyan" highlight />
          <MetricCard label="F1-Score"   value={hybrid.f1_score}   pct={hybrid.f1_score}   color="bg-cyan" highlight />
          <MetricCard label="ROC-AUC"    value={hybrid.roc_auc}    pct={hybrid.roc_auc}    color="bg-cyan" highlight />
          <MetricCard label="MCC"        value={hybrid.mcc}        pct={(hybrid.mcc+1)/2}  color="bg-cyan" highlight
            hint="MCC range: −1 to +1. Best metric for 0.17% fraud imbalance." />
        </div>
      </div>

      {/* Comparison table */}
      <div className="glass-card p-5">
        <div className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Target size={14} className="text-cyan" />
          Model Comparison (Hybrid vs XGBoost-Only vs Isolation Forest-Only)
        </div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Precision</th>
                <th>Recall</th>
                <th>F1</th>
                <th>ROC-AUC</th>
                <th>MCC</th>
                <th className="text-emerald-500">TP</th>
                <th className="text-amber-500">FP</th>
                <th className="text-red-500">FN</th>
                <th>TN</th>
              </tr>
            </thead>
            <tbody>
              {([
                { label: 'Hybrid Fusion ★', m: hybrid, hl: true },
                { label: 'XGBoost Only',    m: xgb,    hl: false },
                { label: 'Isolation Forest',m: ifo,    hl: false },
              ] as const).map(({ label, m, hl }) => (
                <tr key={label} className={hl ? 'bg-cyan/[0.03]' : ''}>
                  <td className={hl ? 'text-cyan font-bold' : 'text-slate-400'}>{label}</td>
                  {(['precision', 'recall', 'f1_score', 'roc_auc', 'mcc'] as const).map(k => (
                    <td key={k} className={`font-mono ${hl ? 'text-white font-semibold' : 'text-slate-500'}`}>
                      {(m as any)[k].toFixed(4)}
                    </td>
                  ))}
                  <td className="font-mono text-emerald-500">{m.confusion_matrix.true_positives.toLocaleString()}</td>
                  <td className="font-mono text-amber-500">{m.confusion_matrix.false_positives.toLocaleString()}</td>
                  <td className="font-mono text-red-500">{m.confusion_matrix.false_negatives.toLocaleString()}</td>
                  <td className="font-mono text-slate-600">{m.confusion_matrix.true_negatives.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Charts row 1: ROC + PR Curve */}
      <div className="grid grid-cols-2 gap-5">
        {/* ROC Curve */}
        <div className="glass-card p-5">
          <div className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
            <TrendingUp size={14} className="text-cyan" /> ROC Curves
          </div>
          <div className="text-xs text-slate-600 mb-4">
            Hybrid AUC <span className="text-cyan font-mono">{roc_curve_data.hybrid.auc.toFixed(4)}</span> ·
            XGB <span className="font-mono">{roc_curve_data.xgb.auc.toFixed(4)}</span> ·
            IF <span className="font-mono">{roc_curve_data.if.auc.toFixed(4)}</span>
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rocData}>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis dataKey="fpr" tickFormatter={v => v.toFixed(2)} tick={{ fill: '#475569', fontSize: 10 }}
                  label={{ value: 'False Positive Rate', position: 'insideBottom', offset: -2, fill: '#475569', fontSize: 10 }} />
                <YAxis tickFormatter={v => v.toFixed(1)} tick={{ fill: '#475569', fontSize: 10 }}
                  label={{ value: 'True Positive Rate', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10 }} />
                <Tooltip formatter={(v: number) => v.toFixed(4)} {...TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <ReferenceLine x={0} y={0} stroke="#1e293b" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="Hybrid"  stroke="#06b6d4" strokeWidth={2.5} dot={false} name={`Hybrid (${roc_curve_data.hybrid.auc.toFixed(4)})`} />
                <Line type="monotone" dataKey="XGBoost" stroke="#10b981" strokeWidth={1.5} dot={false} name={`XGBoost (${roc_curve_data.xgb.auc.toFixed(4)})`} />
                <Line type="monotone" dataKey="IF"      stroke="#f59e0b" strokeWidth={1.5} dot={false} name={`IF (${roc_curve_data.if.auc.toFixed(4)})`} strokeDasharray="4 2" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Precision-Recall Curve */}
        <div className="glass-card p-5">
          <div className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
            <TrendingUp size={14} className="text-cyan" /> Precision-Recall Curve
          </div>
          <div className="text-xs text-slate-600 mb-4">
            More informative than ROC for severely imbalanced datasets (0.17% fraud)
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={prData}>
                <defs>
                  <linearGradient id="prGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#06b6d4" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis dataKey="recall" tickFormatter={v => v.toFixed(1)} tick={{ fill: '#475569', fontSize: 10 }}
                  label={{ value: 'Recall', position: 'insideBottom', offset: -2, fill: '#475569', fontSize: 10 }} />
                <YAxis domain={[0, 1]} tickFormatter={v => v.toFixed(1)} tick={{ fill: '#475569', fontSize: 10 }}
                  label={{ value: 'Precision', angle: -90, position: 'insideLeft', fill: '#475569', fontSize: 10 }} />
                <Tooltip formatter={(v: number) => v.toFixed(4)} {...TOOLTIP_STYLE} />
                <Area type="monotone" dataKey="precision" stroke="#06b6d4" strokeWidth={2} fill="url(#prGrad)" dot={false} name="Precision" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Charts row 2: Bar comparison + Confusion matrix */}
      <div className="grid grid-cols-2 gap-5">
        {/* Grouped bar chart */}
        <div className="glass-card p-5">
          <div className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <BarChart2 size={14} className="text-cyan" /> Metric Comparison (All Models)
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={compData} barCategoryGap="25%" barGap={2}>
                <CartesianGrid strokeDasharray="2 4" />
                <XAxis dataKey="metric" tick={{ fill: '#475569', fontSize: 10 }} />
                <YAxis domain={[0, 1]} tickFormatter={v => v.toFixed(1)} tick={{ fill: '#475569', fontSize: 10 }} />
                <Tooltip formatter={(v: number) => v.toFixed(4)} {...TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="Hybrid"  fill="#06b6d4" radius={[3,3,0,0]} name="Hybrid" />
                <Bar dataKey="XGBoost" fill="#10b981" radius={[3,3,0,0]} name="XGBoost" />
                <Bar dataKey="IF"      fill="#f59e0b" radius={[3,3,0,0]} name="Isolation Forest" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Confusion matrix */}
        <div className="glass-card p-5">
          <div className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Target size={14} className="text-cyan" />
            Confusion Matrix — Hybrid Fusion
            <span className="text-xs text-slate-600 font-normal">(threshold={metrics.decision_thresholds.review})</span>
          </div>
          <ConfusionMatrix cm={hybrid.confusion_matrix} />
        </div>
      </div>

      {/* MCC highlight */}
      <div className="glass-card p-5 border border-cyan/10 bg-gradient-to-r from-cyan/[0.03] to-transparent">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-xl bg-cyan/10 text-cyan flex-shrink-0">
            <Award size={20} />
          </div>
          <div>
            <div className="text-sm font-semibold text-white mb-1">
              Why MCC = <span className="text-gradient-cyan font-mono">{hybrid.mcc.toFixed(4)}</span> is the headline metric
            </div>
            <div className="text-xs text-slate-600 leading-relaxed max-w-3xl">
              With only <strong className="text-slate-400">{metrics.test_fraud_pct.toFixed(4)}% fraud</strong> in the test set,
              accuracy is a misleading metric (a model predicting ALL legitimate would score &gt;99.8% accuracy).
              MCC (Matthews Correlation Coefficient) is the standard metric for severely imbalanced binary classification —
              it accounts for all four cells of the confusion matrix and ranges from −1 (inverse prediction) to +1 (perfect).
              Our hybrid fusion achieves MCC = {hybrid.mcc.toFixed(4)}, demonstrating the superiority of the ensemble approach
              over either component alone (XGB: {xgb.mcc.toFixed(4)}, IF: {ifo.mcc.toFixed(4)}).
            </div>
          </div>
        </div>
      </div>

      {/* Metric explanations */}
      <MetricExplanations />
    </div>
  )
}

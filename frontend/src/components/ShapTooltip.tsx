// src/components/ShapTooltip.tsx
// SHAP hover panel shown below a hovered row in the Live Dashboard.
// Renders a mini bar chart + a human-readable analyst summary.
import type { ShapFeature } from '../types'
import { Brain, AlertTriangle } from 'lucide-react'

interface Props {
  features: ShapFeature[]
  loading?: boolean
  noData?: boolean
}

// ── Human-readable explanations for each feature ─────────────────────────────
function getFeatureExplanation(f: ShapFeature): string {
  const name = f.feature_name.toLowerCase()
  const isRisk = f.shap_value > 0
  const abs = Math.abs(f.shap_value)
  const impact = abs > 0.25 ? 'strongly' : abs > 0.1 ? 'moderately' : 'slightly'

  if (name === 'amount_deviation_z') {
    const sigma = Math.abs(f.feature_value).toFixed(1)
    return isRisk
      ? `Transaction amount is ${sigma}σ above this user's historical average — ${impact} increases fraud risk`
      : `Transaction amount is within normal range for this user — lowers suspicion`
  }
  if (name === 'time_of_day_risk') {
    return isRisk
      ? `Transaction occurred during high-risk hours (midnight–5 AM) — ${impact} increases fraud probability`
      : `Transaction occurred during normal business hours — positive legitimacy signal`
  }
  if (name === 'location_entropy') {
    return isRisk
      ? `Originated from an unrecognized device or location — ${impact} raises suspicion of account takeover`
      : `Originated from a trusted, previously seen device — reduces fraud risk`
  }
  if (name === 'velocity_change') {
    return isRisk
      ? `Unusual spike in transaction velocity vs. recent history — ${impact} flags potential card testing`
      : `Transaction velocity is consistent with the user's historical patterns`
  }
  if (name === 'tx_freq_1h') {
    return isRisk
      ? `Unusually high transaction frequency in the past hour — ${impact} suggests automated fraud attempt`
      : `Transaction frequency in the past hour is within normal bounds`
  }
  if (name === 'tx_freq_24h') {
    return isRisk
      ? `Above-average transactions in the past 24 hours — ${impact} indicates possible velocity abuse`
      : `Daily transaction count is within normal range for this user`
  }
  // PCA features (V1-V28 from ULB dataset)
  if (/^v\d+$/i.test(name)) {
    return isRisk
      ? `Anonymized PCA pattern (${f.feature_name}) strongly associated with historical fraud — ${impact} increases risk score`
      : `Anonymized PCA pattern (${f.feature_name}) is consistent with legitimate transactions`
  }
  // Fallback
  return isRisk
    ? `Feature "${f.feature_name}" indicates elevated fraud risk (${impact} contribution)`
    : `Feature "${f.feature_name}" supports transaction legitimacy (${impact} reduction)`
}

// ── Build a 1-sentence analyst summary from top risk factors ─────────────────
function buildAnalystSummary(features: ShapFeature[]): string {
  const risks = features
    .filter((f) => f.shap_value > 0)
    .sort((a, b) => b.shap_value - a.shap_value)
    .slice(0, 3)

  if (risks.length === 0) {
    return 'No significant risk factors detected. Transaction patterns appear consistent with legitimate behavior.'
  }

  const labels = risks.map((f) => {
    const name = f.feature_name.toLowerCase()
    if (name === 'amount_deviation_z') return `unusually high amount (${Math.abs(f.feature_value).toFixed(1)}σ)`
    if (name === 'time_of_day_risk') return 'off-hours timing'
    if (name === 'location_entropy') return 'unrecognized device'
    if (name === 'velocity_change') return 'velocity spike'
    if (name === 'tx_freq_1h') return 'high hourly frequency'
    if (name === 'tx_freq_24h') return 'elevated daily activity'
    if (/^v\d+$/i.test(name)) return `anomalous PCA pattern (${f.feature_name})`
    return f.feature_name
  })

  if (labels.length === 1) return `Risk signal detected: ${labels[0]}.`
  if (labels.length === 2) return `Two risk signals detected: ${labels[0]} and ${labels[1]}.`
  return `Three risk signals detected: ${labels[0]}, ${labels[1]}, and ${labels[2]}.`
}

export default function ShapTooltip({ features, loading, noData }: Props) {
  if (loading) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-400 py-2">
        <div className="w-4 h-4 border-2 border-cyan border-t-transparent rounded-full animate-spin" />
        <span>Computing SHAP feature contributions…</span>
      </div>
    )
  }

  if (noData || !features || features.length === 0) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500 py-2">
        <Brain size={14} className="text-slate-600" />
        <span>
          An explanation is temporarily unavailable for this transaction. The fraud score remains valid.
        </span>
      </div>
    )
  }

  const sorted = [...features].sort((a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value))
  const maxAbs = Math.max(...sorted.map((f) => Math.abs(f.shap_value)), 0.001)
  const summary = buildAnalystSummary(features)
  const topExplanation = getFeatureExplanation(sorted[0])

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Brain size={14} className="text-cyan" />
        <span className="text-xs font-semibold text-white">SHAP Feature Contributions</span>
        <span className="text-xs text-slate-500 ml-1">— XGBoost TreeExplainer</span>
      </div>

      {/* Analyst summary */}
      <div className="flex items-start gap-2 bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-2.5">
        <AlertTriangle size={13} className="text-amber-400 flex-shrink-0 mt-0.5" />
        <div>
          <div className="text-xs font-medium text-white mb-0.5">{summary}</div>
          <div className="text-xs text-slate-500">{topExplanation}</div>
        </div>
      </div>

      {/* Feature bars */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
        {sorted.slice(0, 8).map((f) => {
          const isRisk = f.shap_value > 0
          const pct = (Math.abs(f.shap_value) / maxAbs) * 100
          const label = f.feature_name
            .replace('amount_deviation_z', 'Amount Z-score')
            .replace('time_of_day_risk', 'Night-time Risk')
            .replace('velocity_change', 'Velocity Change')
            .replace('location_entropy', 'New Device')
            .replace('tx_freq_1h', 'Freq (1h)')
            .replace('tx_freq_24h', 'Freq (24h)')

          return (
            <div key={f.feature_name} className="flex items-center gap-2 min-w-0">
              <div
                className="text-xs font-mono text-slate-400 w-28 flex-shrink-0 truncate"
                title={f.feature_name}
              >
                {label}
              </div>
              <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    isRisk ? 'bg-red-500' : 'bg-emerald-500'
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div
                className={`text-xs font-mono font-semibold w-12 text-right flex-shrink-0 ${
                  isRisk ? 'text-red-400' : 'text-emerald-400'
                }`}
              >
                {isRisk ? '+' : ''}{f.shap_value.toFixed(3)}
              </div>
            </div>
          )
        })}
      </div>
      <div className="text-xs text-slate-600">
        Positive values (red) increase fraud risk · Negative values (green) reduce fraud risk
      </div>
    </div>
  )
}

// src/components/DecisionExplanation.tsx
// AI-powered decision explanation panel using Ollama qwen3:8b (with rule-based fallback)
import { useState, useEffect, useRef } from 'react'
import { Sparkles, Brain, ChevronRight, Loader2, AlertCircle, CheckCircle, XCircle, Clock } from 'lucide-react'
import { explainTransaction } from '../lib/api'
import type { ExplainRequest, ExplainResponse } from '../lib/api'

interface DecisionExplanationProps {
  decisionTier: string
  finalScore: number
  xgbScore?: number
  ifScore?: number
  amount: number
  shapFeatures?: Array<{
    feature_name: string
    shap_value: number
    feature_value: number
    direction: string
    rank: number
  }>
  behavioral?: Record<string, number | null>
}

const tierConfig = {
  APPROVE: {
    icon: <CheckCircle size={16} className="text-emerald-400" />,
    gradient: 'from-emerald-500/10 to-emerald-500/5',
    border: 'border-emerald-500/20',
    badge: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
    label: 'Why APPROVED',
  },
  REVIEW: {
    icon: <Clock size={16} className="text-amber-400" />,
    gradient: 'from-amber-500/10 to-amber-500/5',
    border: 'border-amber-500/20',
    badge: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
    label: 'Why MANUAL REVIEW',
  },
  BLOCK: {
    icon: <XCircle size={16} className="text-red-400" />,
    gradient: 'from-red-500/10 to-red-500/5',
    border: 'border-red-500/20',
    badge: 'bg-red-500/15 text-red-400 border-red-500/25',
    label: 'Why BLOCKED',
  },
} as const

type Tier = keyof typeof tierConfig

export default function DecisionExplanation({
  decisionTier,
  finalScore,
  xgbScore,
  ifScore,
  amount,
  shapFeatures = [],
  behavioral = {},
}: DecisionExplanationProps) {
  const [response, setResponse] = useState<ExplainResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [requested, setRequested] = useState(false)
  const [elapsedSec, setElapsedSec] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const tier = (decisionTier?.toUpperCase() || 'APPROVE') as Tier
  const config = tierConfig[tier] || tierConfig.APPROVE

  const handleGetExplanation = async () => {
    setRequested(true)
    setLoading(true)
    setError(null)
    setElapsedSec(0)
    timerRef.current = setInterval(() => setElapsedSec(s => s + 1), 1000)
    try {
      const payload: ExplainRequest = {
        decision_tier: tier,
        final_score: finalScore,
        xgb_score: xgbScore,
        if_score: ifScore,
        amount,
        shap_features: shapFeatures,
        behavioral: behavioral as Record<string, number>,
      }
      const result = await explainTransaction(payload)
      setResponse(result)
    } catch (err: any) {
      setError('Could not generate explanation. Make sure Ollama is running (ollama serve) and qwen3:8b is installed.')
    } finally {
      setLoading(false)
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }

  if (!requested) {
    return (
      <button
        id="get-ai-explanation-btn"
        onClick={handleGetExplanation}
        className={`
          w-full flex items-center justify-between p-4 rounded-xl border transition-all duration-200
          bg-gradient-to-r ${config.gradient} ${config.border}
          hover:brightness-125 hover:shadow-lg group cursor-pointer
        `}
      >
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded-lg bg-white/5">
            <Sparkles size={15} className="text-cyan animate-pulse" />
          </div>
          <div className="text-left">
            <div className="text-sm font-semibold text-white">{config.label}</div>
            <div className="text-xs text-slate-500 mt-0.5">
              AI explanation powered by Ollama qwen3:8b
            </div>
          </div>
        </div>
        <ChevronRight size={16} className="text-slate-500 group-hover:text-white group-hover:translate-x-0.5 transition-all" />
      </button>
    )
  }

  if (loading) {
    const progress = Math.min((elapsedSec / 60) * 100, 95)
    const isWarmingUp = elapsedSec > 5
    return (
      <div className={`rounded-xl border p-5 bg-gradient-to-br ${config.gradient} ${config.border}`}>
        <div className="flex items-center gap-3 mb-3">
          {config.icon}
          <span className="text-sm font-semibold text-white">{config.label}</span>
        </div>
        <div className="flex items-center gap-3 text-slate-400 text-sm">
          <Loader2 size={15} className="animate-spin text-cyan flex-shrink-0" />
          <div>
            <span>Generating AI explanation via Ollama qwen3:8b…</span>
            <span className="ml-2 font-mono text-slate-500 text-xs">{elapsedSec}s</span>
            {isWarmingUp && (
              <div className="text-xs text-amber-400/70 mt-1">
                ⏳ Model warming up — first request loads qwen3:8b into memory (~30–60s)
              </div>
            )}
          </div>
        </div>
        <div className="mt-3 h-2 bg-white/5 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-cyan/60 to-cyan/30 rounded-full transition-all duration-1000"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/15 p-5 bg-red-500/5">
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle size={14} />
          <span>{error}</span>
        </div>
        <button
          onClick={handleGetExplanation}
          className="mt-2 text-xs text-slate-500 hover:text-slate-300 transition-colors underline"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!response) return null

  return (
    <div className={`rounded-xl border p-5 bg-gradient-to-br ${config.gradient} ${config.border} space-y-3`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {config.icon}
          <span className="text-sm font-semibold text-white">{config.label}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${config.badge}`}>
            {tier}
          </span>
          {response.source === 'ollama' ? (
            <span className="flex items-center gap-1 text-[10px] bg-purple-500/15 text-purple-400 border border-purple-500/25 px-2 py-0.5 rounded-full font-medium">
              <Brain size={9} />
              {response.model ?? 'Ollama'}
            </span>
          ) : (
            <span className="text-[10px] bg-white/5 text-slate-500 border border-white/10 px-2 py-0.5 rounded-full">
              Rule-based
            </span>
          )}
        </div>
      </div>

      {/* Explanation text */}
      <p className="text-sm text-slate-200 leading-relaxed">
        {response.explanation}
      </p>

      {/* Footer note */}
      <div className="flex items-center gap-1.5 pt-1 border-t border-white/5">
        <Sparkles size={10} className="text-slate-600 flex-shrink-0" />
        <p className="text-[10px] text-slate-600">
          {response.source === 'ollama'
            ? `Explanation generated by ${response.model} running locally via Ollama`
            : 'Rule-based explanation · Start Ollama for AI-powered explanations'}
        </p>
      </div>
    </div>
  )
}

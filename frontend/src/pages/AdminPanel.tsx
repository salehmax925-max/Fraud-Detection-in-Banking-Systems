// src/pages/AdminPanel.tsx
import { useState, useEffect } from 'react'
import { Settings, Save, RefreshCw, AlertTriangle, CheckCircle, Sliders, Clock, User } from 'lucide-react'
import { getThresholds, updateThresholds } from '../lib/api'
import type { ThresholdRead } from '../types'
import { useAuth } from '../contexts/AuthContext'

export default function AdminPanel() {
  const { user } = useAuth()
  const [thresholds, setThresholds] = useState<ThresholdRead | null>(null)
  const [blockVal, setBlockVal] = useState(0.85)
  const [reviewVal, setReviewVal] = useState(0.50)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [lastUpdatedDisplay, setLastUpdatedDisplay] = useState<string>('Never updated')

  const fetchThresholds = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getThresholds()
      setThresholds(data)
      setBlockVal(data.block_threshold)
      setReviewVal(data.review_threshold)

      // Build 'Last updated' audit string from the response
      if ((data as any).last_updated_at && (data as any).last_updated_display_name) {
        const d = new Date((data as any).last_updated_at)
        const formatted = d.toLocaleString('en-US', {
          month: 'numeric', day: 'numeric', year: 'numeric',
          hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true
        })
        setLastUpdatedDisplay(`${formatted} by ${(data as any).last_updated_display_name}`)
      } else {
        setLastUpdatedDisplay('Never updated')
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load thresholds')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchThresholds() }, [])

  const handleSave = async () => {
    if (blockVal <= reviewVal) {
      setError('Block threshold must be greater than review threshold')
      return
    }
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      // Format: "username|DisplayName" so backend can parse both
      const byString = user
        ? `${user.username}|${user.display_name}`
        : 'unknown'

      const data = await updateThresholds({
        block_threshold: blockVal,
        review_threshold: reviewVal,
        updated_by: byString,
      })
      setThresholds(data)
      setSuccess(`Thresholds updated — block=${data.block_threshold.toFixed(2)}, review=${data.review_threshold.toFixed(2)}. Takes effect IMMEDIATELY.`)

      // Update the 'Last updated' display immediately (no page refresh)
      const d = new Date()
      const formatted = d.toLocaleString('en-US', {
        month: 'numeric', day: 'numeric', year: 'numeric',
        hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true
      })
      setLastUpdatedDisplay(`${formatted} by ${user?.display_name || 'Unknown'}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to update thresholds')
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = thresholds
    ? Math.abs(blockVal - thresholds.block_threshold) > 0.001 || Math.abs(reviewVal - thresholds.review_threshold) > 0.001
    : false

  // Preview: what tier a given score would get with the new thresholds
  const previewScore = (score: number) =>
    score > blockVal ? 'BLOCK' : score >= reviewVal ? 'REVIEW' : 'APPROVE'

  const previewScores = [0.95, 0.85, 0.75, 0.60, 0.50, 0.40, 0.20, 0.05]

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="section-title">
          <Settings size={22} className="text-cyan" />
          Admin Panel — Live Threshold Configuration
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Adjust fraud detection thresholds in real-time — no retraining required
        </p>
      </div>

      {/* Warning */}
      <div className="flex items-start gap-3 bg-amber-500/8 border border-amber-500/20 rounded-xl p-4 text-sm text-amber-400">
        <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
        <div>
          <strong className="font-semibold">Threshold Impact Warning</strong>
          <div className="text-xs mt-1 opacity-80">
            Lowering thresholds increases fraud caught but raises false positives (customer friction).
            Raising thresholds reduces friction but may miss fraud. Changes take effect immediately for all new transactions.
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-3 bg-red-500/8 border border-red-500/20 rounded-xl p-3 text-sm text-red-400">
          <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />{error}
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 bg-emerald-500/8 border border-emerald-500/20 rounded-xl p-3 text-sm text-emerald-400">
          <CheckCircle size={14} /> {success}
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        {/* Current config */}
        <div className="glass-card p-5">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Sliders size={16} className="text-cyan" /> Current Active Thresholds
          </h2>
          {loading ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm">
              <RefreshCw size={14} className="animate-spin" /> Loading…
            </div>
          ) : thresholds ? (
            <div className="space-y-5">
              {/* BLOCK threshold slider */}
              <div>
                <div className="flex justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium text-red-400">BLOCK Threshold</span>
                  <span className="font-mono text-white font-bold">{blockVal.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min={0.01}
                  max={1.00}
                  step={0.01}
                  value={blockVal}
                  onChange={(e) => setBlockVal(parseFloat(e.target.value))}
                  className="w-full h-2 rounded-full appearance-none cursor-pointer
                             bg-gradient-to-r from-block via-review to-approve
                             accent-block"
                />
                <div className="text-xs text-slate-500 mt-1">
                  Scores above {blockVal.toFixed(2)} → Auto-blocked (BLOCK tier)
                </div>
              </div>

              {/* REVIEW threshold slider */}
              <div>
                <div className="flex justify-between text-xs text-slate-400 mb-2">
                  <span className="font-medium text-amber-400">REVIEW Threshold</span>
                  <span className="font-mono text-white font-bold">{reviewVal.toFixed(2)}</span>
                </div>
                <input
                  type="range"
                  min={0.01}
                  max={blockVal - 0.01}
                  step={0.01}
                  value={reviewVal}
                  onChange={(e) => setReviewVal(parseFloat(e.target.value))}
                  className="w-full h-2 rounded-full appearance-none cursor-pointer accent-yellow-500"
                />
                <div className="text-xs text-slate-500 mt-1">
                  Scores {reviewVal.toFixed(2)}–{blockVal.toFixed(2)} → Analyst review (REVIEW tier)
                </div>
              </div>



              <div className="flex items-center gap-3 pt-2">
                <button
                  onClick={handleSave}
                  disabled={saving || !hasChanges}
                  className="btn-primary flex items-center gap-2 text-sm py-2.5 px-5"
                >
                  <Save size={14} className={saving ? 'animate-pulse' : ''} />
                  {saving ? 'Saving…' : 'Apply Changes'}
                </button>
                <button
                  onClick={() => {
                    setBlockVal(thresholds.block_threshold)
                    setReviewVal(thresholds.review_threshold)
                  }}
                  disabled={!hasChanges}
                  className="btn-ghost text-sm py-2 px-4"
                >
                  Reset
                </button>
                {hasChanges && (
                  <span className="text-xs text-review animate-pulse">Unsaved changes</span>
                )}
              </div>

              {/* Audit trail */}
              <div className="flex items-start gap-2 text-xs pt-2 border-t border-white/5">
                <Clock size={13} className="text-slate-600 flex-shrink-0 mt-0.5" />
                <div className="space-y-0.5">
                  <span className="text-slate-600">Last updated: </span>
                  <span className={lastUpdatedDisplay === 'Never updated' ? 'text-slate-700' : 'text-slate-400'}>
                    {lastUpdatedDisplay}
                  </span>
                </div>
              </div>

              {/* Current editor */}
              {user && (
                <div className="flex items-center gap-2 text-xs text-slate-600 bg-white/[0.02] rounded-xl px-3 py-2 border border-white/[0.04]">
                  <User size={12} className="text-cyan/40" />
                  Saving as: <span className="text-slate-400 font-medium">{user.display_name}</span>
                  <span className="text-slate-700">({user.role})</span>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Score tier preview */}
        <div className="glass-card p-5">
          <h2 className="text-sm font-semibold text-white mb-4">
            Threshold Preview — Score → Tier Mapping
          </h2>
          <div className="text-xs text-slate-500 mb-3">
            How each fraud score would be classified with the current slider values:
          </div>
          <div className="space-y-2">
            {previewScores.map((score) => {
              const tier = previewScore(score)
              return (
                <div key={score} className="flex items-center justify-between py-2 border-b border-white/[0.04] last:border-0">
                  <div className="font-mono text-sm text-white w-16">
                    {score.toFixed(2)}
                  </div>
                  <div className="flex-1 mx-3">
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          tier === 'BLOCK' ? 'score-gradient-block'
                            : tier === 'REVIEW' ? 'score-gradient-review'
                            : 'score-gradient-approve'
                        }`}
                        style={{ width: `${score * 100}%` }}
                      />
                    </div>
                  </div>
                  <span className={`text-xs font-bold w-16 text-right ${
                    tier === 'BLOCK' ? 'text-red-400'
                      : tier === 'REVIEW' ? 'text-amber-400'
                      : 'text-emerald-400'
                  }`}>
                    {tier}
                  </span>
                </div>
              )
            })}
          </div>

          <div className="mt-4 pt-4 border-t border-white/5 text-xs text-slate-600 space-y-1">
            <div>
              <span className="text-red-400 font-medium">BLOCK</span> → score &gt; {blockVal.toFixed(2)} —
              transaction auto-denied, no analyst needed
            </div>
            <div>
              <span className="text-amber-400 font-medium">REVIEW</span> → score {reviewVal.toFixed(2)}–{blockVal.toFixed(2)} —
              routed to analyst review queue
            </div>
            <div>
              <span className="text-emerald-400 font-medium">APPROVE</span> → score &lt; {reviewVal.toFixed(2)} —
              transaction auto-approved
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// src/pages/DigitalTwin.tsx
import { useState, useEffect, useCallback } from 'react'
import {
  User, Search, RefreshCw, Cpu, Shield, Clock,
  TrendingUp, ChevronDown, AlertCircle, Users,
  Activity, Zap, BarChart2,
} from 'lucide-react'
import { getDigitalTwin, getUsers } from '../lib/api'
import type { DigitalTwinSummary, UserListItem } from '../types'

// ── Types and Helpers ──────────────────────────────────────────

// ── Behavioral feature row ──────────────────────────────────────
function FeatureBar({
  label, value, max, fmt, description,
}: { label: string; value: number; max: number; fmt: (v: number) => string; description?: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>{label}</span>
          {description && <span className="text-xs ml-2" style={{ color: 'var(--text-muted)' }}>{description}</span>}
        </div>
        <span className="font-mono font-bold text-sm" style={{ color: 'var(--text-primary)' }}>{fmt(value)}</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-surface)' }}>
        <div
          className="h-full bg-gradient-to-r from-cyan-500/60 to-blue-500/60 rounded-full transition-all duration-1000 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

// ── Risk trend indicator ────────────────────────────────────────
function RiskIndicator({ value }: { value: number | null }) {
  if (value === null) return <span className="text-sm" style={{ color: 'var(--text-muted)' }}>No data</span>
  const pct = (value * 100).toFixed(1)
  const isHigh = value > 0.7
  const isMid  = value > 0.4
  const color  = isHigh ? 'text-red-400' : isMid ? 'text-amber-400' : 'text-emerald-400'
  const label  = isHigh ? 'High Risk — Investigate' : isMid ? 'Moderate — Monitor' : 'Low — Normal Behavior'
  const barColor = isHigh ? 'from-red-500 to-red-400' : isMid ? 'from-amber-500 to-amber-400' : 'from-emerald-500 to-emerald-400'

  return (
    <div className="space-y-2">
      <div className={`text-2xl font-extrabold ${color}`}>{pct}%</div>
      <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--bg-surface)' }}>
        <div
          className={`h-full bg-gradient-to-r ${barColor} rounded-full transition-all duration-1000`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</div>
    </div>
  )
}

export default function DigitalTwinPage() {
  const [userId, setUserId] = useState('')
  const [inputValue, setInputValue] = useState('')  // controlled input separate from loaded userId
  const [profile, setProfile] = useState<DigitalTwinSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [users, setUsers] = useState<UserListItem[]>([])
  const [loadingUsers, setLoadingUsers] = useState(true)
  const [showDropdown, setShowDropdown] = useState(false)
  const [isDemoMode, setIsDemoMode] = useState(false)

  const loadProfile = useCallback(async (uid: string) => {
    if (!uid.trim()) return
    setLoading(true)
    setError(null)
    setProfile(null)
    setUserId(uid)
    try {
      const data = await getDigitalTwin(uid.trim())
      setProfile(data)
      setIsDemoMode(false)
    } catch (err: any) {
      const status = err.response?.status
      setProfile(null)
      setIsDemoMode(false)
      if (status === 404) {
        setError(err.response?.data?.detail || `No transaction history found for user '${uid}'. Score at least one transaction for this user first.`)
      } else if (!err.response) {
        setError('Cannot connect to backend server. Make sure the backend is running on http://localhost:8000')
      } else {
        setError(err.response?.data?.detail || 'Failed to load profile')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    getUsers()
      .then((data) => {
        setUsers(data)
        setIsDemoMode(false)
        if (data.length > 0) {
          setInputValue(data[0].user_id)
          loadProfile(data[0].user_id)
        }
      })
      .catch(() => {
        setUsers([])
        setIsDemoMode(false)
        setError('Cannot connect to backend server. Make sure the backend is running.')
      })
      .finally(() => setLoadingUsers(false))
  }, [loadProfile])

  const [dropdownFilter, setDropdownFilter] = useState('')

  const normalizeUserId = (raw: string): string => {
    const trimmed = raw.trim().toLowerCase()
    if (/^\d+$/.test(trimmed)) {
      const num = parseInt(trimmed, 10)
      if (num >= 0 && num < 2000) {
        return `user_${num.toString().padStart(4, '0')}`
      }
    }
    if (/^user_\d+$/.test(trimmed)) {
      const numStr = trimmed.replace('user_', '')
      const num = parseInt(numStr, 10)
      if (num >= 0 && num < 2000) {
        return `user_${num.toString().padStart(4, '0')}`
      }
    }
    return trimmed
  }

  const handleSearch = () => {
    if (inputValue.trim()) {
      const norm = normalizeUserId(inputValue)
      setInputValue(norm)
      loadProfile(norm)
    }
  }

  const handleSelectUser = (uid: string) => {
    setInputValue(uid)
    setShowDropdown(false)
    setDropdownFilter('')
    loadProfile(uid)
  }

  const allUsers = users
  const displayedUsers = dropdownFilter.trim()
    ? allUsers.filter((u) => u.user_id.toLowerCase().includes(dropdownFilter.trim().toLowerCase()))
    : allUsers

  return (
    <div className="p-6 space-y-5 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="section-title">
          <div className="p-2 rounded-xl bg-purple-500/10 text-purple-400"><User size={18} /></div>
          Digital Twin
          <span className="text-sm font-normal ml-1" style={{ color: 'var(--text-muted)' }}>User Behavioral Profile</span>
        </h1>
        <p className="text-sm mt-1.5" style={{ color: 'var(--text-muted)' }}>
          Live per-user behavioral state · Welford's online algorithm · Causal sliding windows ·{' '}
          {isDemoMode && <span className="text-amber-500 font-medium">Demo Data</span>}
        </p>
      </div>

      {/* Disclaimer */}
      <div className="flex items-start gap-2.5 rounded-xl p-3 text-xs" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
        <AlertCircle size={12} className="flex-shrink-0 mt-0.5" style={{ color: 'var(--text-muted)' }} />
        <span>
          <strong style={{ color: 'var(--text-secondary)' }}>Note:</strong> User IDs are <em>synthetic proxies</em> generated by hash-bucketing
          transaction Time + Amount into 2,000 buckets. The ULB dataset has no native user/device/geo fields — this is a
          documented limitation in the thesis.
        </span>
      </div>

      {/* Search & user selector */}
      <div className="glass-card p-5">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Enter synthetic user ID (e.g. user_0042)"
              className="form-input w-full pl-10"
            />
            <User size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-muted)' }} />
          </div>

          {allUsers.length > 0 && (
            <div className="relative">
              <button
                onClick={() => setShowDropdown(!showDropdown)}
                className="btn-ghost flex items-center gap-2 py-2.5 px-4 text-sm"
              >
                <Users size={13} />
                {loadingUsers ? 'Loading…' : `${allUsers.length} users`}
                <ChevronDown size={13} className={`transition-transform duration-200 ${showDropdown ? 'rotate-180' : ''}`} />
              </button>
              {showDropdown && (
                <div className="absolute top-full mt-1 right-0 z-50 w-72 rounded-2xl shadow-2xl overflow-hidden"
                  style={{ background: isDemoMode ? '#0d1526' : 'var(--bg-secondary)', border: '1px solid var(--border)' }}
                >
                  <div className="p-2 border-b" style={{ borderColor: 'var(--border)' }}>
                    <input
                      type="text"
                      value={dropdownFilter}
                      onChange={(e) => setDropdownFilter(e.target.value)}
                      placeholder="Filter users (e.g. 0414)..."
                      className="form-input w-full py-1.5 px-3 text-xs rounded-lg"
                      autoFocus
                    />
                  </div>
                  <div className="max-h-60 overflow-y-auto">
                    {displayedUsers.slice(0, 100).map((u) => (
                      <button
                        key={u.user_id}
                        onClick={() => handleSelectUser(u.user_id)}
                        className={`w-full flex items-center justify-between px-4 py-2.5 text-sm hover:bg-white/5 transition-colors text-left ${
                          u.user_id === userId ? 'text-cyan-400' : ''
                        }`}
                        style={{ color: u.user_id === userId ? undefined : 'var(--text-secondary)' }}
                      >
                        <span className="font-mono text-xs">{u.user_id}</span>
                        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{u.transaction_count} tx</span>
                      </button>
                    ))}
                    {displayedUsers.length === 0 && (
                      <div className="p-4 text-center text-xs text-slate-500">No user found matching "{dropdownFilter}"</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          <button
            onClick={handleSearch}
            disabled={loading || !inputValue.trim()}
            className="btn-primary flex items-center gap-2 py-2.5 px-5 text-sm"
          >
            {loading ? <RefreshCw size={13} className="animate-spin" /> : <Search size={13} />}
            {loading ? 'Loading…' : 'Load Profile'}
          </button>
        </div>

        <div className="mt-3 text-xs flex items-center gap-2" style={{ color: 'var(--text-muted)' }}>
          {loadingUsers ? (
            <><RefreshCw size={9} className="animate-spin" /> Discovering users…</>
          ) : allUsers.length > 0 ? (
            <><Users size={9} className="text-cyan-400/60" /> {allUsers.length} users with transaction history — select from dropdown or type ID</>
          ) : (
            <><AlertCircle size={9} className="text-amber-500/70" /> No users yet — run a simulation on the Live Dashboard first</>
          )}
        </div>
      </div>

      {/* Click-away */}
      {showDropdown && (
        <div className="fixed inset-0 z-40" onClick={() => setShowDropdown(false)} />
      )}

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-500/8 border border-red-500/20 rounded-xl p-4 text-sm text-red-400">
          <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
          <div>{error}</div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && (
        <div className="glass-card p-6 space-y-4 animate-pulse">
          <div className="h-6 rounded-lg shimmer w-48" />
          <div className="grid grid-cols-4 gap-4">
            {[1,2,3,4].map(i => <div key={i} className="h-20 rounded-xl shimmer" />)}
          </div>
        </div>
      )}

      {/* Profile */}
      {profile && !loading && (
        <div className="space-y-5 animate-slide-up">
          {/* Hero card */}
          <div className="glass-card p-6" style={{ border: '1px solid rgba(168,85,247,0.15)', background: 'linear-gradient(135deg, rgba(168,85,247,0.04) 0%, transparent 100%)' }}>
            <div className="flex items-start justify-between mb-5">
              <div className="flex items-center gap-4">
                <div className="relative">
                  <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center shadow-[0_4px_20px_rgba(139,92,246,0.3)]">
                    <User size={22} className="text-white" />
                  </div>
                  <div className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-emerald-400 border-2 border-[#0a1020] flex items-center justify-center">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-200 animate-pulse" />
                  </div>
                </div>
                <div>
                  <div className="font-mono text-2xl font-extrabold tracking-tight" style={{ color: 'var(--text-primary)' }}>{profile.user_id}</div>
                  <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>Synthetic proxy ID · hash-bucketed Time+Amount</div>
                  {isDemoMode && (
                    <span className="inline-flex items-center gap-1 text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-full mt-1">
                      ⚡ Demo Profile
                    </span>
                  )}
                </div>
              </div>
              {profile.updated_at && (
                <div className="text-xs flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
                  <Clock size={11} />
                  Updated {new Date(profile.updated_at).toLocaleString()}
                </div>
              )}
            </div>

            <div className="grid grid-cols-4 gap-4">
              {[
                { label: 'Total Transactions', value: profile.total_transactions.toString(), icon: <Activity size={15} />, color: 'text-cyan-400' },
                { label: 'Last 24h Activity', value: `${profile.last_24h_tx_count} tx`, icon: <Clock size={15} />, color: 'text-blue-400' },
                { label: 'Known Devices', value: `${profile.known_device_count} markers`, icon: <Cpu size={15} />, color: 'text-purple-400' },
                { label: 'Risk Trend (EMA)', value: null, icon: <Zap size={15} />, color: profile.current_risk_trend ? (profile.current_risk_trend > 0.7 ? 'text-red-400' : profile.current_risk_trend > 0.4 ? 'text-amber-400' : 'text-emerald-400') : 'text-slate-600' },
              ].map((card, i) => (
                <div key={i} className="rounded-xl p-4" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                  <div className={`flex items-center gap-1.5 ${card.color} mb-2`}>{card.icon}<span className="text-xs font-medium">{card.label}</span></div>
                  {card.value !== null ? (
                    <div className={`text-2xl font-extrabold ${card.color}`}>{card.value}</div>
                  ) : (
                    <RiskIndicator value={profile.current_risk_trend} />
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-5">
            {/* Amount Statistics */}
            <div className="glass-card p-5">
              <h2 className="text-sm font-semibold mb-5 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                <TrendingUp size={14} className="text-cyan-400" />
                Amount Statistics
                <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>Welford's online algorithm</span>
              </h2>
              <div className="space-y-5">
                <FeatureBar
                  label="Transaction Count"
                  value={profile.amount_stats.count}
                  max={profile.amount_stats.count}
                  fmt={v => v.toLocaleString()}
                  description="total observed"
                />
                <FeatureBar
                  label="Mean Amount"
                  value={profile.amount_stats.mean}
                  max={profile.amount_stats.mean + profile.amount_stats.std * 3}
                  fmt={v => `$${v.toFixed(2)}`}
                  description="rolling average"
                />
                <FeatureBar
                  label="Std Deviation"
                  value={profile.amount_stats.std}
                  max={profile.amount_stats.mean + profile.amount_stats.std * 3}
                  fmt={v => `$${v.toFixed(2)}`}
                  description="behavioral spread"
                />
                <div className="pt-3" style={{ borderTop: '1px solid var(--border)' }}>
                  <div className="flex justify-between text-xs mb-1" style={{ color: 'var(--text-muted)' }}>
                    <span>Amount Z-score threshold: ±2σ</span>
                    <span className="font-mono">${(profile.amount_stats.mean + 2 * profile.amount_stats.std).toFixed(2)}</span>
                  </div>
                  <div className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                    Amounts beyond ±2σ trigger <code className="text-cyan-400/70 font-mono text-[10px]">amount_deviation_z</code> as a SHAP fraud signal.
                    Welford's algorithm computes mean & variance without storing all historical amounts (O(1) memory).
                  </div>
                </div>
              </div>
            </div>

            {/* Known Devices */}
            <div className="glass-card p-5">
              <h2 className="text-sm font-semibold mb-5 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                <Cpu size={14} className="text-cyan-400" />
                Known Device / Region Markers
              </h2>
              {profile.known_devices.length === 0 ? (
                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>No device markers recorded yet</div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {profile.known_devices.map((device, i) => (
                    <div
                      key={i}
                      className="rounded-xl px-3 py-2 text-xs font-mono flex items-center gap-2"
                      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400/60 flex-shrink-0" />
                      {device}
                      {i === 0 && <span className="text-[9px] text-emerald-500/80 ml-0.5">primary</span>}
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-4 p-3 rounded-xl text-xs leading-relaxed" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                Devices are <em>synthetic</em>: daily hash-bucketed from user_id + day_bin.
                A new bucket = <code className="text-cyan-400/60">location_entropy=1</code> (binary fraud signal, rank 8 in SHAP).
                A known bucket = <code className="text-cyan-400/60">location_entropy=0</code>.
              </div>

              {/* How the DT works */}
              <div className="mt-4 space-y-3">
                <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Thesis Section 2.3</div>
                {[
                  { icon: <BarChart2 size={11} />, title: 'Causal Windows', desc: 'tx_freq_1h/24h use sliding deques — only past data, no future leakage.' },
                  { icon: <Shield size={11} />, title: 'No Training Skew', desc: 'Same BehavioralFeatureEngine class used at training AND inference time.' },
                  { icon: <Activity size={11} />, title: 'O(1) Memory', desc: "Welford's algorithm + fixed deques: infinite-scale profiling without growing storage." },
                ].map(({ icon, title, desc }) => (
                  <div key={title} className="flex items-start gap-2.5 rounded-lg p-2.5" style={{ background: 'var(--bg-surface)' }}>
                    <span className="text-cyan-400/60 mt-0.5 flex-shrink-0">{icon}</span>
                    <div>
                      <div className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>{title}</div>
                      <div className="text-[11px] mt-0.5 leading-relaxed" style={{ color: 'var(--text-muted)' }}>{desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

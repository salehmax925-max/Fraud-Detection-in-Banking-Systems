// src/pages/SystemLogsPage.tsx
import { useState, useEffect } from 'react'
import { RefreshCw, AlertCircle, Info, AlertTriangle, Terminal } from 'lucide-react'
import axios from 'axios'

interface LogEntry {
  id: number
  log_level: string
  event_type: string
  username?: string
  display_name?: string
  description?: string
  created_at: string
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  login_success:        'Login Success',
  login_failure:        'Login Failed',
  logout:               'Logout',
  transaction_submitted:'Transaction',
  threshold_changed:    'Threshold Change',
  role_changed:         'Role Change',
  governance_change:    'Governance',
  csv_export:           'CSV Export',
  access_denied:        'Access Denied',
}

function LogLevelIcon({ level }: { level: string }) {
  if (level === 'WARNING') return <AlertTriangle size={13} className="text-yellow-400" />
  if (level === 'ERROR')   return <AlertCircle size={13} className="text-red-400" />
  return <Info size={13} className="text-cyan-400" />
}

function LogLevelBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    INFO:    'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
    WARNING: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
    ERROR:   'bg-red-500/10 text-red-400 border-red-500/20',
  }
  const s = styles[level] || styles.INFO
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${s}`}>
      {level}
    </span>
  )
}

export default function SystemLogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState('')
  const [filterLevel, setFilterLevel] = useState('')
  const [error, setError] = useState('')

  const fetchLogs = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { limit: '200' }
      if (filterType) params.event_type = filterType
      if (filterLevel) params.log_level = filterLevel
      const resp = await axios.get('/api/logs', { params, withCredentials: true })
      setLogs(resp.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to load logs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchLogs() }, [filterType, filterLevel])

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleString('en-US', {
      year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: false
    })

  const uniqueEventTypes = [...new Set(logs.map(l => l.event_type).filter(Boolean))]

  return (
    <div className="p-6 space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-slate-500/10 border border-slate-500/20 flex items-center justify-center">
            <Terminal size={18} className="text-slate-400" />
          </div>
          <div>
            <h1 className="text-white text-xl font-bold">System Logs</h1>
            <p className="text-slate-500 text-xs">Admin-only event audit trail</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Level filter */}
          <select
            value={filterLevel}
            onChange={e => setFilterLevel(e.target.value)}
            className="px-3 py-2 rounded-xl text-xs bg-slate-900 border border-white/[0.08] text-slate-300 focus:outline-none focus:border-cyan-500/40"
          >
            <option value="">All Levels</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>

          {/* Event type filter */}
          <select
            value={filterType}
            onChange={e => setFilterType(e.target.value)}
            className="px-3 py-2 rounded-xl text-xs bg-slate-900 border border-white/[0.08] text-slate-300 focus:outline-none focus:border-cyan-500/40"
          >
            <option value="">All Events</option>
            {Object.entries(EVENT_TYPE_LABELS).map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>

          <button
            onClick={fetchLogs}
            className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.06] text-slate-400 hover:text-white text-sm transition-all"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-xl bg-red-500/8 border border-red-500/20 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Log Table */}
      <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
        <div className="px-6 py-3 border-b border-white/[0.06] flex items-center justify-between">
          <span className="text-slate-500 text-xs">{logs.length} log entries</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-6 h-6 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : logs.length === 0 ? (
          <div className="text-center py-12 text-slate-600 text-sm">No log entries found</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[10px] text-slate-600 uppercase tracking-wider border-b border-white/[0.04]">
                  <th className="text-left px-6 py-2.5 font-medium">Timestamp</th>
                  <th className="text-center px-4 py-2.5 font-medium">Level</th>
                  <th className="text-left px-4 py-2.5 font-medium">Event</th>
                  <th className="text-left px-4 py-2.5 font-medium">User</th>
                  <th className="text-left px-6 py-2.5 font-medium">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.03]">
                {logs.map(log => (
                  <tr key={log.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-6 py-2.5 font-mono text-slate-600 whitespace-nowrap">
                      {fmtDate(log.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <LogLevelBadge level={log.log_level} />
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <LogLevelIcon level={log.log_level} />
                        <span className="text-slate-300 font-medium">
                          {EVENT_TYPE_LABELS[log.event_type] || log.event_type}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      {log.username ? (
                        <div className="flex flex-col">
                          <span className="text-white">{log.display_name || log.username}</span>
                          <span className="text-slate-700 text-[10px]">@{log.username}</span>
                        </div>
                      ) : (
                        <span className="text-slate-700">—</span>
                      )}
                    </td>
                    <td className="px-6 py-2.5 text-slate-500 max-w-xs truncate" title={log.description || ''}>
                      {log.description || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

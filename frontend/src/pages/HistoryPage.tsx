// src/pages/HistoryPage.tsx
import { useState, useEffect } from 'react'
import { Download, ChevronLeft, ChevronRight, Search, Filter, Calendar, DollarSign } from 'lucide-react'
import axios from 'axios'
import { useAuth } from '../contexts/AuthContext'

type DecisionTier = 'BLOCK' | 'REVIEW' | 'APPROVE' | ''

interface TxItem {
  id: number
  transaction_uuid: string
  synthetic_user_id?: string
  auth_user_id?: number
  amount: number
  decision_tier?: string
  xgb_score?: number
  if_score?: number
  final_score?: number
  is_simulation: boolean
  true_label?: number
  created_at: string
}

interface PaginatedHistory {
  items: TxItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

function TierBadge({ tier }: { tier?: string }) {
  if (!tier) return <span className="text-slate-600">—</span>
  const styles = {
    BLOCK:   'bg-red-500/15 text-red-300 border-red-500/25',
    REVIEW:  'bg-yellow-500/15 text-yellow-300 border-yellow-500/25',
    APPROVE: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  }[tier] || 'bg-slate-500/15 text-slate-400 border-slate-500/25'

  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${styles}`}>
      {tier}
    </span>
  )
}

function Score({ v }: { v?: number | null }) {
  if (v === undefined || v === null) return <span className="text-slate-600">—</span>
  const color = v >= 0.85 ? 'text-red-400' : v >= 0.50 ? 'text-yellow-400' : 'text-emerald-400'
  return <span className={`font-mono ${color}`}>{(v * 100).toFixed(1)}%</span>
}

export default function HistoryPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [data, setData] = useState<PaginatedHistory | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [decisionTier, setDecisionTier] = useState<DecisionTier>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [minAmount, setMinAmount] = useState('')
  const [maxAmount, setMaxAmount] = useState('')
  const [exporting, setExporting] = useState(false)
  const [showFilters, setShowFilters] = useState(false)

  const fetchHistory = async (p = page) => {
    setLoading(true)
    try {
      const params: Record<string, string> = {
        page: String(p),
        page_size: '20',
      }
      if (decisionTier) params.decision_tier = decisionTier
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      if (minAmount) params.min_amount = minAmount
      if (maxAmount) params.max_amount = maxAmount

      const resp = await axios.get('/api/history/transactions', { params, withCredentials: true })
      setData(resp.data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchHistory(1)
    setPage(1)
  }, [decisionTier, dateFrom, dateTo, minAmount, maxAmount])

  const handlePageChange = (newPage: number) => {
    setPage(newPage)
    fetchHistory(newPage)
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const params: Record<string, string> = {}
      if (decisionTier) params.decision_tier = decisionTier
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo

      const resp = await axios.get('/api/history/export-csv', {
        params,
        withCredentials: true,
        responseType: 'blob',
      })

      const url = window.URL.createObjectURL(new Blob([resp.data]))
      const link = document.createElement('a')
      link.href = url
      const cd = resp.headers['content-disposition'] || ''
      const name = cd.split('filename=')[1]?.replace(/"/g, '') || 'transactions.csv'
      link.setAttribute('download', name)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Export failed', e)
    } finally {
      setExporting(false)
    }
  }

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleString('en-US', {
      month: 'numeric', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit', hour12: true
    })

  return (
    <div className="p-6 space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-white text-xl font-bold">Transaction History</h1>
          <p className="text-slate-500 text-xs mt-0.5">
            {isAdmin ? 'All system transactions' : 'Your transactions'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.06] text-slate-400 hover:text-white text-sm transition-all"
          >
            <Filter size={14} />
            Filters
          </button>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium text-white transition-all disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)', boxShadow: '0 4px 14px rgba(6,182,212,0.25)' }}
          >
            <Download size={14} />
            {exporting ? 'Exporting...' : 'Export CSV'}
          </button>
        </div>
      </div>

      {/* Filters Panel */}
      {showFilters && (
        <div
          className="rounded-2xl p-5 space-y-4"
          style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <h3 className="text-white text-sm font-semibold">Filter Transactions</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {/* Decision Tier */}
            <div className="space-y-1.5">
              <label className="text-xs text-slate-500 uppercase tracking-wider">Decision</label>
              <select
                value={decisionTier}
                onChange={e => setDecisionTier(e.target.value as DecisionTier)}
                className="w-full px-3 py-2 rounded-xl text-sm bg-slate-900 border border-white/[0.08] text-white focus:outline-none focus:border-cyan-500/40"
              >
                <option value="">All</option>
                <option value="BLOCK">Block</option>
                <option value="REVIEW">Review</option>
                <option value="APPROVE">Approve</option>
              </select>
            </div>

            {/* Date From */}
            <div className="space-y-1.5">
              <label className="text-xs text-slate-500 uppercase tracking-wider">From Date</label>
              <input
                type="date"
                value={dateFrom}
                onChange={e => setDateFrom(e.target.value)}
                className="w-full px-3 py-2 rounded-xl text-sm bg-slate-900 border border-white/[0.08] text-white focus:outline-none focus:border-cyan-500/40"
              />
            </div>

            {/* Date To */}
            <div className="space-y-1.5">
              <label className="text-xs text-slate-500 uppercase tracking-wider">To Date</label>
              <input
                type="date"
                value={dateTo}
                onChange={e => setDateTo(e.target.value)}
                className="w-full px-3 py-2 rounded-xl text-sm bg-slate-900 border border-white/[0.08] text-white focus:outline-none focus:border-cyan-500/40"
              />
            </div>

            {/* Amount Range */}
            <div className="space-y-1.5">
              <label className="text-xs text-slate-500 uppercase tracking-wider">Amount Range</label>
              <div className="flex gap-1">
                <input
                  type="number"
                  placeholder="Min"
                  value={minAmount}
                  onChange={e => setMinAmount(e.target.value)}
                  className="w-full px-2 py-2 rounded-xl text-sm bg-slate-900 border border-white/[0.08] text-white focus:outline-none focus:border-cyan-500/40"
                />
                <input
                  type="number"
                  placeholder="Max"
                  value={maxAmount}
                  onChange={e => setMaxAmount(e.target.value)}
                  className="w-full px-2 py-2 rounded-xl text-sm bg-slate-900 border border-white/[0.08] text-white focus:outline-none focus:border-cyan-500/40"
                />
              </div>
            </div>
          </div>
          <button
            onClick={() => {
              setDecisionTier('')
              setDateFrom('')
              setDateTo('')
              setMinAmount('')
              setMaxAmount('')
            }}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            Clear all filters
          </button>
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
        <div className="px-6 py-3 border-b border-white/[0.06] flex items-center justify-between">
          <span className="text-slate-500 text-xs">
            {data ? `${data.total} transaction${data.total !== 1 ? 's' : ''}` : 'Loading...'}
          </span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="w-6 h-6 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-600 uppercase tracking-wider border-b border-white/[0.04]">
                  <th className="text-left px-6 py-3 font-medium">Transaction ID</th>
                  {isAdmin && <th className="text-left px-4 py-3 font-medium">User</th>}
                  <th className="text-right px-4 py-3 font-medium">Amount</th>
                  <th className="text-center px-4 py-3 font-medium">Decision</th>
                  {isAdmin && <th className="text-center px-4 py-3 font-medium">XGB</th>}
                  {isAdmin && <th className="text-center px-4 py-3 font-medium">IF</th>}
                  <th className="text-center px-4 py-3 font-medium">Final Score</th>
                  <th className="text-left px-4 py-3 font-medium">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.03]">
                {data?.items.length === 0 ? (
                  <tr>
                    <td colSpan={isAdmin ? 8 : 5} className="text-center py-12 text-slate-600">
                      No transactions found
                    </td>
                  </tr>
                ) : data?.items.map(tx => (
                  <tr key={tx.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-6 py-3">
                      <div className="flex flex-col">
                        <span className="text-white font-mono text-xs">
                          {tx.transaction_uuid.slice(0, 8)}...
                        </span>
                        {tx.is_simulation && (
                          <span className="text-[10px] text-slate-600">simulation</span>
                        )}
                      </div>
                    </td>
                    {isAdmin && (
                      <td className="px-4 py-3 text-slate-500 text-xs font-mono">
                        {tx.synthetic_user_id?.slice(0, 10) || tx.auth_user_id || '—'}
                      </td>
                    )}
                    <td className="px-4 py-3 text-right text-white font-medium">
                      ${tx.amount.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <TierBadge tier={tx.decision_tier} />
                    </td>
                    {isAdmin && (
                      <td className="px-4 py-3 text-center">
                        <Score v={tx.xgb_score} />
                      </td>
                    )}
                    {isAdmin && (
                      <td className="px-4 py-3 text-center">
                        <Score v={tx.if_score} />
                      </td>
                    )}
                    <td className="px-4 py-3 text-center">
                      <Score v={tx.final_score} />
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs">
                      {fmtDate(tx.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-between px-6 py-3 border-t border-white/[0.04]">
            <span className="text-xs text-slate-600">
              Page {data.page} of {data.total_pages}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handlePageChange(page - 1)}
                disabled={page <= 1}
                className="p-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.06] text-slate-400 disabled:opacity-30 transition-all"
              >
                <ChevronLeft size={14} />
              </button>
              {Array.from({ length: Math.min(5, data.total_pages) }, (_, i) => {
                const p = Math.max(1, Math.min(data.total_pages - 4, page - 2)) + i
                return (
                  <button
                    key={p}
                    onClick={() => handlePageChange(p)}
                    className={`w-7 h-7 text-xs rounded-lg transition-all ${
                      p === page
                        ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30'
                        : 'text-slate-500 hover:text-white hover:bg-white/[0.04] border border-transparent'
                    }`}
                  >
                    {p}
                  </button>
                )
              })}
              <button
                onClick={() => handlePageChange(page + 1)}
                disabled={page >= data.total_pages}
                className="p-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.06] text-slate-400 disabled:opacity-30 transition-all"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

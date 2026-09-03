// src/pages/GovernancePage.tsx
import { useState, useEffect } from 'react'
import { Shield, RefreshCw, Edit2, Key, Power, Check, X, ChevronDown } from 'lucide-react'
import axios from 'axios'

interface GovUser {
  id: number
  username: string
  display_name: string
  role: string
  is_active: boolean
  last_login?: string
  permissions?: {
    can_view_personal_data: boolean
    can_edit_thresholds: boolean
    can_view_all_transactions: boolean
  }
}

interface AuditEntry {
  id: number
  changed_by: string
  target_username: string
  change_type: string
  previous_value?: string
  new_value?: string
  created_at: string
}

interface ToggleBtnProps {
  value: boolean
  onChange: () => void
  disabled?: boolean
}

function Toggle({ value, onChange, disabled }: ToggleBtnProps) {
  return (
    <button
      onClick={onChange}
      disabled={disabled}
      className={`relative w-10 h-5 rounded-full transition-all duration-200 flex-shrink-0
        ${value ? 'bg-cyan-500' : 'bg-slate-700'}
        ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer hover:scale-105'}
      `}
    >
      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all duration-200
        ${value ? 'left-5.5' : 'left-0.5'}`}
        style={{ left: value ? '22px' : '2px' }}
      />
    </button>
  )
}

function RoleBadge({ role }: { role: string }) {
  const styles = {
    admin: 'bg-blue-500/15 text-blue-300 border-blue-500/25',
    user:  'bg-slate-500/15 text-slate-300 border-slate-500/25',
    ceo:   'bg-yellow-500/15 text-yellow-300 border-yellow-500/25',
  }[role] || 'bg-slate-500/15 text-slate-400 border-slate-500/25'

  const labels: Record<string, string> = { admin: 'Admin', user: 'User', ceo: 'Data Manager' }

  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold border ${styles}`}>
      {labels[role] || role}
    </span>
  )
}

export default function GovernancePage() {
  const [users, setUsers] = useState<GovUser[]>([])
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingRole, setEditingRole] = useState<number | null>(null)
  const [resetPwdUser, setResetPwdUser] = useState<number | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState('')

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const fetchData = async () => {
    setLoading(true)
    try {
      const [usersRes, auditRes] = await Promise.all([
        axios.get('/api/governance/users', { withCredentials: true }),
        axios.get('/api/governance/audit-log', { withCredentials: true }),
      ])
      setUsers(usersRes.data)
      setAuditLog(auditRes.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to load governance data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  const changeRole = async (userId: number, newRole: string) => {
    setSaving(true)
    try {
      await axios.put(`/api/governance/users/${userId}/role`, { new_role: newRole }, { withCredentials: true })
      showToast(`Role updated to ${newRole}`)
      setEditingRole(null)
      fetchData()
    } catch (e: any) {
      showToast('Failed: ' + (e?.response?.data?.detail || 'Error'))
    } finally {
      setSaving(false)
    }
  }

  const togglePermission = async (userId: number, perm: string, value: boolean) => {
    try {
      await axios.put(`/api/governance/users/${userId}/permissions`, { [perm]: !value }, { withCredentials: true })
      showToast('Permission updated')
      fetchData()
    } catch (e: any) {
      showToast('Failed: ' + (e?.response?.data?.detail || 'Error'))
    }
  }

  const toggleActive = async (userId: number) => {
    try {
      await axios.post(`/api/governance/users/${userId}/toggle-active`, {}, { withCredentials: true })
      showToast('Account status updated')
      fetchData()
    } catch (e: any) {
      showToast('Failed: ' + (e?.response?.data?.detail || 'Error'))
    }
  }

  const resetPassword = async (userId: number) => {
    if (!newPassword.trim()) return
    setSaving(true)
    try {
      await axios.post(`/api/governance/users/${userId}/reset-password`, { new_password: newPassword }, { withCredentials: true })
      showToast('Password reset successfully')
      setResetPwdUser(null)
      setNewPassword('')
    } catch (e: any) {
      showToast('Failed: ' + (e?.response?.data?.detail || 'Error'))
    } finally {
      setSaving(false)
    }
  }

  const fmtDate = (iso?: string) => {
    if (!iso) return '—'
    return new Date(iso).toLocaleString('en-US', {
      month: 'numeric', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true
    })
  }

  const changeTypeLabel: Record<string, string> = {
    role_change: 'Role Change',
    permission_change: 'Permission',
    password_reset: 'Password Reset',
    account_disable: 'Account Disabled',
    account_enable: 'Account Enabled',
    governance_change: 'Governance',
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Toast */}
      {toast && (
        <div className="fixed top-6 right-6 z-50 px-5 py-3 rounded-xl bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 text-sm font-medium shadow-lg animate-slide-in">
          {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-yellow-500/10 border border-yellow-500/20 flex items-center justify-center">
            <Shield size={18} className="text-yellow-400" />
          </div>
          <div>
            <h1 className="text-white text-xl font-bold">Governance Management</h1>
            <p className="text-slate-500 text-xs">Data Manager — CEO Access Only</p>
          </div>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.06] text-slate-400 hover:text-white text-sm transition-all"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="px-4 py-3 rounded-xl bg-red-500/8 border border-red-500/20 text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* User Management Table */}
      <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
        <div className="px-6 py-4 border-b border-white/[0.06] flex items-center gap-2">
          <h2 className="text-white font-semibold text-sm">User Management</h2>
          <span className="text-slate-600 text-xs">({users.filter(u => u.role !== 'ceo').length} users)</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-600 uppercase tracking-wider border-b border-white/[0.04]">
                <th className="text-left px-6 py-3 font-medium">User</th>
                <th className="text-left px-4 py-3 font-medium">Role</th>
                <th className="text-center px-4 py-3 font-medium">View Personal</th>
                <th className="text-center px-4 py-3 font-medium">Edit Thresholds</th>
                <th className="text-center px-4 py-3 font-medium">View All Txns</th>
                <th className="text-left px-4 py-3 font-medium">Last Login</th>
                <th className="text-center px-4 py-3 font-medium">Status</th>
                <th className="text-right px-6 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.03]">
              {users.map(u => (
                <tr key={u.id} className="hover:bg-white/[0.02] transition-colors">
                  <td className="px-6 py-4">
                    <div className="flex flex-col">
                      <span className="text-white font-medium">{u.display_name}</span>
                      <span className="text-slate-600 text-xs">@{u.username}</span>
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    {editingRole === u.id ? (
                      <div className="flex items-center gap-2">
                        <select
                          className="bg-slate-900 text-white text-xs rounded-lg border border-cyan-500/30 px-2 py-1 focus:outline-none"
                          defaultValue={u.role}
                          onChange={e => changeRole(u.id, e.target.value)}
                          disabled={saving}
                        >
                          <option value="admin">Admin</option>
                          <option value="user">User</option>
                        </select>
                        <button onClick={() => setEditingRole(null)} className="text-slate-500 hover:text-red-400 transition-colors">
                          <X size={13} />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <RoleBadge role={u.role} />
                        {u.role !== 'ceo' && (
                          <button
                            onClick={() => setEditingRole(u.id)}
                            className="text-slate-700 hover:text-slate-400 transition-colors"
                            title="Edit role"
                          >
                            <Edit2 size={11} />
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-4 text-center">
                    <div className="flex justify-center">
                      <Toggle
                        value={u.permissions?.can_view_personal_data ?? false}
                        onChange={() => togglePermission(u.id, 'can_view_personal_data', u.permissions?.can_view_personal_data ?? false)}
                        disabled={u.role === 'ceo'}
                      />
                    </div>
                  </td>
                  <td className="px-4 py-4 text-center">
                    <div className="flex justify-center">
                      <Toggle
                        value={u.permissions?.can_edit_thresholds ?? false}
                        onChange={() => togglePermission(u.id, 'can_edit_thresholds', u.permissions?.can_edit_thresholds ?? false)}
                        disabled={u.role === 'ceo'}
                      />
                    </div>
                  </td>
                  <td className="px-4 py-4 text-center">
                    <div className="flex justify-center">
                      <Toggle
                        value={u.permissions?.can_view_all_transactions ?? false}
                        onChange={() => togglePermission(u.id, 'can_view_all_transactions', u.permissions?.can_view_all_transactions ?? false)}
                        disabled={u.role === 'ceo'}
                      />
                    </div>
                  </td>
                  <td className="px-4 py-4 text-slate-500 text-xs">
                    {fmtDate(u.last_login)}
                  </td>
                  <td className="px-4 py-4 text-center">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${u.is_active
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
                      {u.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-2">
                      {/* Reset Password */}
                      {resetPwdUser === u.id ? (
                        <div className="flex items-center gap-2">
                          <input
                            type="password"
                            value={newPassword}
                            onChange={e => setNewPassword(e.target.value)}
                            placeholder="New password"
                            className="w-32 px-2 py-1 text-xs rounded-lg bg-slate-900 border border-cyan-500/30 text-white focus:outline-none"
                          />
                          <button
                            onClick={() => resetPassword(u.id)}
                            disabled={saving}
                            className="text-emerald-400 hover:text-emerald-300"
                            title="Confirm"
                          >
                            <Check size={13} />
                          </button>
                          <button
                            onClick={() => { setResetPwdUser(null); setNewPassword('') }}
                            className="text-slate-500 hover:text-red-400"
                            title="Cancel"
                          >
                            <X size={13} />
                          </button>
                        </div>
                      ) : (
                        <>
                          <button
                            onClick={() => setResetPwdUser(u.id)}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-slate-500 hover:text-white hover:bg-white/[0.06] border border-transparent hover:border-white/[0.08] transition-all"
                            title="Reset password"
                          >
                            <Key size={11} />
                            Reset PW
                          </button>
                          {u.role !== 'ceo' && (
                            <button
                              onClick={() => toggleActive(u.id)}
                              className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs border transition-all
                                ${u.is_active
                                  ? 'text-red-400 hover:bg-red-500/10 border-transparent hover:border-red-500/20'
                                  : 'text-emerald-400 hover:bg-emerald-500/10 border-transparent hover:border-emerald-500/20'
                                }`}
                              title={u.is_active ? 'Disable account' : 'Enable account'}
                            >
                              <Power size={11} />
                              {u.is_active ? 'Disable' : 'Enable'}
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Governance Audit Log */}
      <div className="rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
        <div className="px-6 py-4 border-b border-white/[0.06]">
          <h2 className="text-white font-semibold text-sm">Audit Log</h2>
          <p className="text-slate-600 text-xs mt-0.5">All governance changes are logged here</p>
        </div>

        {auditLog.length === 0 ? (
          <div className="px-6 py-10 text-center text-slate-600 text-sm">
            No governance changes recorded yet
          </div>
        ) : (
          <div className="divide-y divide-white/[0.03] max-h-80 overflow-y-auto">
            {auditLog.map(entry => (
              <div key={entry.id} className="px-6 py-3 flex items-start gap-4 text-xs hover:bg-white/[0.02] transition-colors">
                <span className="text-slate-600 font-mono flex-shrink-0 min-w-[160px]">
                  {fmtDate(entry.created_at)}
                </span>
                <span className="text-slate-400 font-medium flex-shrink-0">
                  CEO ({entry.changed_by})
                </span>
                <span className="text-slate-500">
                  {changeTypeLabel[entry.change_type] || entry.change_type}
                  {' → '}
                  <span className="text-white font-medium">@{entry.target_username}</span>
                  {entry.previous_value && entry.new_value && (
                    <span className="text-slate-600">
                      {' '}({entry.previous_value} → {entry.new_value})
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

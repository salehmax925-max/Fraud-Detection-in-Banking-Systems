// src/components/Layout.tsx
import { useState, useEffect } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  Shield, Activity, ClipboardList, User, Settings,
  BarChart2, ChevronLeft, ChevronRight, Wifi, WifiOff, Zap,
  History, FileText, Users, LogOut, Upload, MessageSquare,
  Sun, Moon,
} from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'

// Nav items defined per role
const ADMIN_NAV = [
  { path: '/',            label: 'Live Dashboard',    icon: <Activity size={18} />,     desc: 'Monitor & simulate' },
  { path: '/review',      label: 'Review Queue',      icon: <ClipboardList size={18} />, desc: 'Analyst decisions' },
  { path: '/twin',        label: 'Digital Twin',      icon: <User size={18} />,          desc: 'Behavioral profiles' },
  { path: '/performance', label: 'Model Performance', icon: <BarChart2 size={18} />,     desc: 'Metrics & ROC curves' },
  { path: '/history',     label: 'History',           icon: <History size={18} />,       desc: 'Transaction history' },
  { path: '/data-import', label: 'Data Import',       icon: <Upload size={18} />,        desc: 'CSV data ingestion' },
  { path: '/admin',       label: 'Threshold Settings',icon: <Settings size={18} />,      desc: 'Threshold controls' },
  { path: '/logs',        label: 'System Logs',       icon: <FileText size={18} />,      desc: 'Event audit trail' },
  { path: '/chat',        label: 'AI Assistant',      icon: <MessageSquare size={18} />, desc: 'Chat with your data' },
]

const USER_NAV = [
  { path: '/',            label: 'Live Dashboard',    icon: <Activity size={18} />,     desc: 'Monitor transactions' },
  { path: '/history',     label: 'My Transactions',   icon: <History size={18} />,       desc: 'Your transaction history' },
  { path: '/admin',       label: 'Threshold Settings',icon: <Settings size={18} />,      desc: 'View thresholds' },
  { path: '/chat',        label: 'AI Assistant',      icon: <MessageSquare size={18} />, desc: 'Chat with your data' },
]

const CEO_NAV = [
  { path: '/governance',  label: 'Governance',        icon: <Shield size={18} />,        desc: 'User management' },
  { path: '/governance',  label: 'User Management',   icon: <Users size={18} />,         desc: 'Roles & permissions' },
  { path: '/chat',        label: 'AI Assistant',      icon: <MessageSquare size={18} />, desc: 'Chat with your data' },
]

function RoleBadge({ role }: { role: string }) {
  const styles = {
    admin: 'bg-blue-500/15 text-blue-300 border-blue-500/25',
    user:  'bg-slate-500/15 text-slate-400 border-slate-500/25',
    ceo:   'bg-yellow-500/15 text-yellow-300 border-yellow-500/25',
  }[role] || 'bg-slate-500/15 text-slate-400 border-slate-500/25'

  const labels: Record<string, string> = { admin: 'Admin', user: 'User', ceo: 'Data Manager' }

  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${styles} uppercase tracking-wider`}>
      {labels[role] || role}
    </span>
  )
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [online, setOnline] = useState<boolean | null>(null)
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { theme, toggleTheme, isDark } = useTheme()

  const navItems = user?.role === 'admin'
    ? ADMIN_NAV
    : user?.role === 'ceo'
    ? CEO_NAV
    : USER_NAV

  // Deduplicate CEO nav
  const uniqueNavItems = navItems.filter((item, idx, arr) =>
    arr.findIndex(a => a.label === item.label) === idx
  )

  // Backend health check
  useEffect(() => {
    let mounted = true
    const check = async () => {
      try {
        const r = await fetch('/api/health', { signal: AbortSignal.timeout(3000) })
        if (mounted) setOnline(r.ok)
      } catch {
        if (mounted) setOnline(false)
      }
    }
    check()
    const id = setInterval(check, 10000)
    return () => { mounted = false; clearInterval(id) }
  }, [])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="flex flex-col h-screen bg-mesh overflow-hidden">
      {/* Top Navigation Bar */}
      <header
        className="flex-shrink-0 flex items-center justify-between px-5 py-2.5 z-10"
        style={{
          background: isDark ? 'rgba(6,9,15,0.92)' : 'rgba(255,255,255,0.95)',
          backdropFilter: 'blur(12px)',
          borderBottom: `1px solid ${isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.07)'}`,
          boxShadow: isDark ? '0 1px 0 rgba(6,182,212,0.06)' : '0 1px 0 rgba(0,0,0,0.06)',
        }}
      >
        {/* Left: System name */}
        <div className="flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)' }}
          >
            <Shield size={14} className="text-white" />
          </div>
          <span className="font-bold text-sm" style={{ color: 'var(--text-primary)' }}>FraudShield AI</span>
          <span className="hidden sm:block text-xs" style={{ color: 'var(--text-muted)' }}>— Al-Balqa Applied University</span>
        </div>

        {/* Right: Theme toggle + User info + logout */}
        <div className="flex items-center gap-3">
          {/* Theme Toggle */}
          <button
            onClick={toggleTheme}
            title={isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
            className="flex items-center justify-center w-8 h-8 rounded-xl transition-all duration-200"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              color: 'var(--text-muted)',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--text-primary)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-muted)')}
          >
            {isDark ? <Sun size={14} /> : <Moon size={14} />}
          </button>

          {user && (
            <div className="flex items-center gap-2">
              <div className="text-right hidden sm:block">
                <div className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>{user.display_name}</div>
                <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>@{user.username}</div>
              </div>
              <RoleBadge role={user.role} />
            </div>
          )}
          <button
            id="btn-logout"
            onClick={handleLogout}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs border border-transparent hover:border-red-500/20 hover:bg-red-500/8 hover:text-red-400 transition-all"
            style={{ color: 'var(--text-muted)' }}
          >
            <LogOut size={13} />
            <span className="hidden sm:block">Logout</span>
          </button>
        </div>
      </header>

      {/* Body: Sidebar + Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside
          className={`relative flex flex-col flex-shrink-0 transition-all duration-300 ease-in-out ${collapsed ? 'w-[68px]' : 'w-[230px]'}`}
          style={{
            background: isDark ? 'rgba(10,16,32,0.92)' : 'rgba(248,250,252,0.98)',
            backdropFilter: 'blur(20px)',
            borderRight: `1px solid var(--border)`,
          }}
        >
          {/* Top glow accent */}
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-400/40 to-transparent" />

          {/* Nav */}
          <nav className="flex-1 px-2 py-4 space-y-0.5 overflow-y-auto">
            {uniqueNavItems.map((item) => {
              const isActive = location.pathname === item.path
              const isChatItem = item.path === '/chat'
              return (
                <NavLink
                  key={item.label}
                  to={item.path}
                  title={collapsed ? item.label : undefined}
                  className={`
                    group flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 font-medium text-sm
                    ${collapsed ? 'justify-center' : ''}
                    ${isActive
                      ? 'bg-gradient-to-r from-cyan-500/10 to-blue-500/5 border border-cyan-500/20 shadow-[0_0_20px_rgba(6,182,212,0.06)]'
                      : isChatItem
                        ? 'border border-dashed border-purple-500/25 bg-purple-500/5'
                        : ''
                    }
                  `}
                  style={{
                    color: isActive
                      ? 'var(--text-primary)'
                      : isChatItem
                        ? '#a78bfa'
                        : 'var(--text-muted)',
                  }}
                >
                  <span className={`flex-shrink-0 transition-colors duration-200 ${isActive ? 'text-cyan-400' : isChatItem ? 'text-purple-400' : ''}`}>
                    {item.icon}
                  </span>
                  {!collapsed && (
                    <span className="truncate">{item.label}</span>
                  )}
                  {!collapsed && isActive && (
                    <div className="ml-auto w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_rgba(6,182,212,0.8)]" />
                  )}
                </NavLink>
              )
            })}
          </nav>

          {/* Status Panel */}
          {!collapsed && (
            <div className="px-3 pb-3 space-y-2">
              {/* Connection status */}
              <div className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs border transition-all duration-500
                ${online === null
                  ? 'border-white/5 text-slate-600'
                  : online
                  ? 'bg-emerald-500/5 border-emerald-500/15 text-emerald-500'
                  : 'bg-amber-500/5 border-amber-500/15 text-amber-500'
                }`}
                style={{ background: online === null ? 'var(--bg-surface)' : undefined }}
              >
                {online === null ? (
                  <><div className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-pulse" /><span>Connecting…</span></>
                ) : online ? (
                  <><Wifi size={11} /><span className="font-medium">Backend Online</span></>
                ) : (
                  <><WifiOff size={11} /><span className="font-medium">Demo Mode</span></>
                )}
              </div>

              {/* Model info */}
              <div className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                <Zap size={11} className="text-cyan-400/60" />
                <span>XGB 0.70 + IF 0.30</span>
              </div>

              {/* Theme label */}
              <div className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs cursor-pointer transition-all"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}
                onClick={toggleTheme}
              >
                {isDark ? <Moon size={11} className="text-blue-400" /> : <Sun size={11} className="text-amber-400" />}
                <span>{isDark ? 'Dark Mode' : 'Light Mode'}</span>
                <span className="ml-auto text-[10px] opacity-60">toggle</span>
              </div>
            </div>
          )}

          {/* Collapse button */}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="mx-2 mb-3 flex items-center justify-center py-2 rounded-xl transition-all duration-200"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              color: 'var(--text-muted)',
            }}
          >
            {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
          </button>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto" style={{ background: 'var(--bg-primary)' }}>
          {/* Offline warning bar */}
          {online === false && (
            <div className="flex items-center gap-3 bg-amber-500/8 border-b border-amber-500/15 px-6 py-2.5 text-xs text-amber-400">
              <WifiOff size={13} />
              <span>
                <strong>Backend offline</strong> — showing demo data.
                Start the backend: <code className="font-mono bg-black/20 px-1.5 py-0.5 rounded">cd backend && uvicorn app.main:app --reload --port 8000</code>
              </span>
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  )
}

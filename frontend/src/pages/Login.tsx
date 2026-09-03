// src/pages/Login.tsx
import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Shield, Eye, EyeOff, Lock, User, AlertCircle, Zap } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login, isAuthenticated, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // Redirect if already logged in
  useEffect(() => {
    if (isAuthenticated && user) {
      const from = (location.state as any)?.from?.pathname
      if (user.role === 'ceo') {
        navigate('/governance', { replace: true })
      } else {
        navigate(from || '/', { replace: true })
      }
    }
  }, [isAuthenticated, user, navigate, location])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!username.trim() || !password.trim()) {
      setError('Please enter both username and password')
      return
    }

    setLoading(true)
    try {
      await login(username.trim(), password)
      // Redirect handled by useEffect above
    } catch (err: any) {
      if (!err?.response) {
        setError('Cannot reach backend server. Please make sure the backend is running on http://localhost:8000')
      } else if (err?.response?.data?.detail) {
        setError(err.response.data.detail)
      } else {
        setError('Invalid username or password')
      }
    } finally {
      setLoading(false)
    }
  }

  const selectDemoUser = (demoUser: string, demoPass: string = '2004') => {
    setUsername(demoUser)
    setPassword(demoPass)
    setError('')
  }

  return (
    <div className="min-h-screen bg-[#06090f] flex items-center justify-center relative overflow-hidden">
      {/* Animated background */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[600px] h-[600px] bg-cyan-500/[0.04] rounded-full blur-3xl animate-pulse" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[500px] h-[500px] bg-blue-600/[0.05] rounded-full blur-3xl animate-pulse" style={{ animationDelay: '1s' }} />
        <div className="absolute top-[40%] right-[20%] w-[300px] h-[300px] bg-violet-500/[0.03] rounded-full blur-3xl animate-pulse" style={{ animationDelay: '2s' }} />

        {/* Grid lines */}
        <div className="absolute inset-0" style={{
          backgroundImage: `
            linear-gradient(rgba(6,182,212,0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(6,182,212,0.03) 1px, transparent 1px)
          `,
          backgroundSize: '60px 60px'
        }} />
      </div>

      {/* Floating particles */}
      <div className="absolute inset-0 pointer-events-none">
        {[...Array(12)].map((_, i) => (
          <div
            key={i}
            className="absolute w-1 h-1 bg-cyan-400/20 rounded-full animate-ping"
            style={{
              left: `${10 + (i * 7.5) % 85}%`,
              top: `${15 + (i * 13) % 70}%`,
              animationDelay: `${i * 0.4}s`,
              animationDuration: `${2 + (i % 3)}s`,
            }}
          />
        ))}
      </div>

      {/* Login Card */}
      <div className="relative w-full max-w-md px-4">
        <div
          className="relative rounded-2xl overflow-hidden"
          style={{
            background: 'linear-gradient(135deg, rgba(10,16,32,0.95) 0%, rgba(6,9,15,0.98) 100%)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(6,182,212,0.12)',
            boxShadow: '0 0 0 1px rgba(255,255,255,0.04), 0 24px 80px rgba(0,0,0,0.6), 0 0 100px rgba(6,182,212,0.05)',
          }}
        >
          {/* Top glow line */}
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-400/50 to-transparent" />

          <div className="p-8 sm:p-10">
            {/* Logo */}
            <div className="flex flex-col items-center mb-8">
              <div className="relative mb-4">
                <div
                  className="w-16 h-16 rounded-2xl flex items-center justify-center"
                  style={{
                    background: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
                    boxShadow: '0 8px 32px rgba(6,182,212,0.4)',
                  }}
                >
                  <Shield size={32} className="text-white" />
                </div>
                <div
                  className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-cyan-400 border-2 border-[#06090f] animate-pulse"
                  style={{ boxShadow: '0 0 10px rgba(6,182,212,0.8)' }}
                />
              </div>

              <h1 className="text-white text-xl font-bold text-center leading-tight">
                Fraud Detection System
              </h1>
              <p className="text-slate-500 text-sm text-center mt-1 font-medium">
                Al-Balqa Applied University
              </p>
              <div className="flex items-center gap-1.5 mt-2 px-3 py-1 rounded-full bg-cyan-500/8 border border-cyan-500/15">
                <Zap size={11} className="text-cyan-400" />
                <span className="text-cyan-400 text-[10px] font-medium uppercase tracking-wider">
                  XGB + Isolation Forest AI
                </span>
              </div>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Error message */}
              {error && (
                <div
                  className="flex items-center gap-2.5 px-4 py-3 rounded-xl text-sm text-red-300"
                  style={{
                    background: 'rgba(239,68,68,0.08)',
                    border: '1px solid rgba(239,68,68,0.2)',
                  }}
                >
                  <AlertCircle size={15} className="flex-shrink-0 text-red-400" />
                  <span>{error}</span>
                </div>
              )}

              {/* Username */}
              <div className="space-y-1.5">
                <label htmlFor="username" className="text-slate-400 text-xs font-medium uppercase tracking-wider">
                  Username
                </label>
                <div className="relative">
                  <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-600">
                    <User size={16} />
                  </div>
                  <input
                    id="username"
                    type="text"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder="Enter your username"
                    autoComplete="username"
                    autoFocus
                    className="w-full pl-10 pr-4 py-3 rounded-xl text-sm text-white placeholder-slate-600
                               focus:outline-none transition-all duration-200"
                    style={{
                      background: 'rgba(255,255,255,0.04)',
                      border: '1px solid rgba(255,255,255,0.08)',
                    }}
                    onFocus={e => {
                      e.target.style.border = '1px solid rgba(6,182,212,0.35)'
                      e.target.style.background = 'rgba(6,182,212,0.04)'
                    }}
                    onBlur={e => {
                      e.target.style.border = '1px solid rgba(255,255,255,0.08)'
                      e.target.style.background = 'rgba(255,255,255,0.04)'
                    }}
                  />
                </div>
              </div>

              {/* Password */}
              <div className="space-y-1.5">
                <label htmlFor="password" className="text-slate-400 text-xs font-medium uppercase tracking-wider">
                  Password
                </label>
                <div className="relative">
                  <div className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-600">
                    <Lock size={16} />
                  </div>
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="Enter your password"
                    autoComplete="current-password"
                    className="w-full pl-10 pr-12 py-3 rounded-xl text-sm text-white placeholder-slate-600
                               focus:outline-none transition-all duration-200"
                    style={{
                      background: 'rgba(255,255,255,0.04)',
                      border: '1px solid rgba(255,255,255,0.08)',
                    }}
                    onFocus={e => {
                      e.target.style.border = '1px solid rgba(6,182,212,0.35)'
                      e.target.style.background = 'rgba(6,182,212,0.04)'
                    }}
                    onBlur={e => {
                      e.target.style.border = '1px solid rgba(255,255,255,0.08)'
                      e.target.style.background = 'rgba(255,255,255,0.04)'
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400 transition-colors"
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              {/* Sign In button */}
              <button
                id="btn-signin"
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-xl font-semibold text-sm text-white
                           relative overflow-hidden transition-all duration-200
                           disabled:opacity-60 disabled:cursor-not-allowed
                           hover:scale-[1.01] active:scale-[0.99] mt-2"
                style={{
                  background: loading
                    ? 'rgba(6,182,212,0.4)'
                    : 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)',
                  boxShadow: loading ? 'none' : '0 4px 24px rgba(6,182,212,0.35)',
                }}
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Signing in...
                  </span>
                ) : (
                  'Sign In'
                )}
              </button>
            </form>

            {/* Quick Demo Accounts */}
            <div className="mt-6 pt-5 border-t border-white/[0.06]">
              <div className="flex items-center justify-between mb-2.5">
                <span className="text-slate-400 text-xs font-medium">Demo Accounts</span>
                <span className="text-cyan-400/80 text-[11px]">Password: <code className="font-mono font-bold text-cyan-300">2004</code></span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => selectDemoUser('saleh')}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 bg-white/[0.03] hover:bg-cyan-500/10 hover:text-cyan-300 border border-white/[0.06] hover:border-cyan-500/30 transition-all text-left flex items-center justify-between"
                >
                  <span>saleh</span>
                  <span className="text-[10px] text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-500/20">Admin</span>
                </button>
                <button
                  type="button"
                  onClick={() => selectDemoUser('amin')}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 bg-white/[0.03] hover:bg-cyan-500/10 hover:text-cyan-300 border border-white/[0.06] hover:border-cyan-500/30 transition-all text-left flex items-center justify-between"
                >
                  <span>amin</span>
                  <span className="text-[10px] text-cyan-400 bg-cyan-950/60 px-1.5 py-0.5 rounded border border-cyan-500/20">Admin</span>
                </button>
                <button
                  type="button"
                  onClick={() => selectDemoUser('user1')}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 bg-white/[0.03] hover:bg-cyan-500/10 hover:text-cyan-300 border border-white/[0.06] hover:border-cyan-500/30 transition-all text-left flex items-center justify-between"
                >
                  <span>user1</span>
                  <span className="text-[10px] text-slate-400 bg-slate-800/60 px-1.5 py-0.5 rounded border border-slate-700/50">User</span>
                </button>
                <button
                  type="button"
                  onClick={() => selectDemoUser('hussain')}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-300 bg-white/[0.03] hover:bg-cyan-500/10 hover:text-cyan-300 border border-white/[0.06] hover:border-cyan-500/30 transition-all text-left flex items-center justify-between"
                >
                  <span>hussain</span>
                  <span className="text-[10px] text-purple-400 bg-purple-950/60 px-1.5 py-0.5 rounded border border-purple-500/20">CEO</span>
                </button>
              </div>
            </div>

            {/* Footer */}
            <div className="mt-6 pt-4 border-t border-white/[0.05]">
              <p className="text-slate-700 text-xs text-center">
                Graduation Project 2024/2025 — Faculty of AI
              </p>
            </div>
          </div>
        </div>

        {/* Bottom hint text */}
        <p className="text-slate-800 text-xs text-center mt-4">
          Protected system — authorized personnel only
        </p>
      </div>
    </div>
  )
}

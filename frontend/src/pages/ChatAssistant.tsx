// src/pages/ChatAssistant.tsx
// AI Chat Assistant — natural language interface for fraud DB + system knowledge
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  MessageSquare, Send, Trash2, RefreshCw, Brain,
  Database, BookOpen, Zap, ChevronDown, Shield,
  Activity, BarChart2, AlertCircle, Sparkles,
} from 'lucide-react'
import { sendChatMessage, clearChatHistory } from '../lib/api'
import type { ChatMessage } from '../lib/api'

// ── Quick question chips ─────────────────────────────────────────
const QUICK_QUESTIONS = [
  { label: '📊 Transaction count', question: 'How many total transactions are in the system?', category: 'data' },
  { label: '🔴 Blocked today', question: 'How many transactions were blocked?', category: 'data' },
  { label: '💰 Average amounts', question: 'What is the average transaction amount by decision tier?', category: 'data' },
  { label: '👥 Top users', question: 'Show me the top 5 most active users', category: 'data' },
  { label: '🤖 XGBoost explained', question: 'How does XGBoost work in this fraud system?', category: 'system' },
  { label: '🔍 What is SHAP?', question: 'Explain SHAP values and how they work', category: 'system' },
  { label: '👤 Digital Twin', question: 'What is the Digital Twin engine?', category: 'system' },
  { label: '📈 Model performance', question: 'What are the model performance metrics?', category: 'system' },
  { label: '🗃️ Dataset info', question: 'Tell me about the training dataset used', category: 'system' },
  { label: '⚙️ Thresholds', question: 'How do the fraud detection thresholds work?', category: 'system' },
]

// ── Typing indicator ──────────────────────────────────────────────
function TypingIndicator() {
  return (
    <div className="flex items-end gap-3 animate-fade-in">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center flex-shrink-0">
        <Brain size={14} className="text-white" />
      </div>
      <div className="chat-bubble-ai flex items-center gap-1.5 px-4 py-3">
        <div className="typing-dot w-2 h-2 rounded-full bg-cyan-400" />
        <div className="typing-dot w-2 h-2 rounded-full bg-cyan-400" />
        <div className="typing-dot w-2 h-2 rounded-full bg-cyan-400" />
      </div>
    </div>
  )
}

// ── Source badge ──────────────────────────────────────────────────
function SourceBadge({ source }: { source?: string }) {
  if (!source) return null
  const cfg: Record<string, { label: string; icon: JSX.Element; className: string }> = {
    pandasai:       { label: 'PandasAI', icon: <Database size={9} />, className: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20' },
    knowledge_base: { label: 'Knowledge Base', icon: <BookOpen size={9} />, className: 'text-purple-400 bg-purple-400/10 border-purple-400/20' },
    rule_based:     { label: 'Data Query', icon: <Activity size={9} />, className: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' },
    ollama:         { label: 'Ollama AI', icon: <Zap size={9} />, className: 'text-amber-400 bg-amber-400/10 border-amber-400/20' },
  }
  const c = cfg[source]
  if (!c) return null
  return (
    <span className={`inline-flex items-center gap-1 text-[9px] font-semibold px-1.5 py-0.5 rounded border ${c.className}`}>
      {c.icon} {c.label}
    </span>
  )
}

// ── Message bubble ────────────────────────────────────────────────
function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'

  // Simple markdown-like rendering
  const renderContent = (content: string) => {
    const lines = content.split('\n')
    return lines.map((line, i) => {
      // Headers
      if (line.startsWith('**') && line.endsWith('**')) {
        return <p key={i} className="font-bold text-sm mb-1" style={{ color: 'var(--text-primary)' }}>{line.replace(/\*\*/g, '')}</p>
      }
      // Bold inline
      const parts = line.split(/(\*\*[^*]+\*\*)/)
      const rendered = parts.map((part, j) =>
        part.startsWith('**') ? <strong key={j}>{part.replace(/\*\*/g, '')}</strong> : part
      )
      // Code
      if (line.includes('`')) {
        const codeParts = line.split(/(`[^`]+`)/)
        return (
          <p key={i} className="text-sm mb-0.5">
            {codeParts.map((p, j) =>
              p.startsWith('`')
                ? <code key={j} className="text-cyan-400 bg-cyan-400/10 px-1 rounded text-[11px] font-mono">{p.slice(1,-1)}</code>
                : p
            )}
          </p>
        )
      }
      // Bullet
      if (line.startsWith('- ') || line.startsWith('• ')) {
        return (
          <div key={i} className="flex items-start gap-1.5 mb-0.5 text-sm">
            <span className="text-cyan-400/60 mt-0.5 flex-shrink-0">•</span>
            <span>{rendered}</span>
          </div>
        )
      }
      // Table row
      if (line.startsWith('|')) {
        return <code key={i} className="block text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>{line}</code>
      }
      // Empty
      if (!line.trim()) return <div key={i} className="h-2" />
      return <p key={i} className="text-sm mb-0.5">{rendered}</p>
    })
  }

  return (
    <div className={`flex items-end gap-3 ${isUser ? 'flex-row-reverse animate-slide-in-right' : 'animate-slide-in-left'}`}>
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0 ${
        isUser
          ? 'bg-gradient-to-br from-cyan-500 to-blue-600'
          : msg.error
            ? 'bg-red-500/20 border border-red-500/30'
            : 'bg-gradient-to-br from-purple-500 to-blue-600'
      }`}>
        {isUser
          ? <span className="text-white text-xs font-bold">U</span>
          : msg.error
            ? <AlertCircle size={14} className="text-red-400" />
            : <Brain size={14} className="text-white" />
        }
      </div>

      {/* Bubble */}
      <div className={`max-w-[85%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        {isUser ? (
          <div className="chat-bubble-user">
            <p className="text-sm">{msg.content}</p>
          </div>
        ) : (
          <div className={`chat-bubble-ai ${msg.error ? 'border-red-500/20' : ''}`}>
            <div className="space-y-0.5">
              {renderContent(msg.content)}
            </div>
          </div>
        )}
        {/* Source + time */}
        <div className={`flex items-center gap-2 px-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
          {!isUser && <SourceBadge source={msg.source} />}
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
            {new Date(msg.created_at).toLocaleTimeString()}
          </span>
        </div>
      </div>
    </div>
  )
}

// ── Welcome screen ────────────────────────────────────────────────
function WelcomeScreen({ onQuickQuestion }: { onQuickQuestion: (q: string) => void }) {
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? QUICK_QUESTIONS : QUICK_QUESTIONS.slice(0, 6)

  return (
    <div className="flex flex-col items-center justify-center h-full py-12 px-6 space-y-8 animate-fade-in">
      {/* Hero */}
      <div className="text-center space-y-4">
        <div className="relative inline-block">
          <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center shadow-[0_8px_40px_rgba(139,92,246,0.35)] mx-auto">
            <Sparkles size={32} className="text-white" />
          </div>
          <div className="absolute -top-1 -right-1 w-6 h-6 rounded-full bg-cyan-400 border-2 flex items-center justify-center" style={{ borderColor: 'var(--bg-primary)' }}>
            <Brain size={12} className="text-white" />
          </div>
        </div>
        <div>
          <h2 className="text-2xl font-extrabold" style={{ color: 'var(--text-primary)' }}>FraudShield AI Assistant</h2>
          <p className="text-sm mt-2 max-w-md" style={{ color: 'var(--text-muted)' }}>
            Ask me anything about your fraud data or how the system works.
            I query the live database and explain AI decisions in plain language.
          </p>
        </div>
      </div>

      {/* Capabilities */}
      <div className="grid grid-cols-3 gap-4 w-full max-w-2xl">
        {[
          { icon: <Database size={18} className="text-cyan-400" />, title: 'Live Data', desc: 'Query transactions, scores, users from the database', bg: 'from-cyan-500/10 to-transparent', border: 'border-cyan-500/20' },
          { icon: <BookOpen size={18} className="text-purple-400" />, title: 'System Knowledge', desc: 'Understand XGBoost, SHAP, Digital Twin, thresholds', bg: 'from-purple-500/10 to-transparent', border: 'border-purple-500/20' },
          { icon: <Shield size={18} className="text-emerald-400" />, title: 'Always Available', desc: 'Works offline with knowledge base, no API key needed', bg: 'from-emerald-500/10 to-transparent', border: 'border-emerald-500/20' },
        ].map(({ icon, title, desc, bg, border }) => (
          <div key={title} className={`rounded-2xl p-4 border bg-gradient-to-br ${bg} ${border}`}>
            <div className="mb-2">{icon}</div>
            <div className="text-sm font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>{title}</div>
            <div className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>{desc}</div>
          </div>
        ))}
      </div>

      {/* Quick questions */}
      <div className="w-full max-w-2xl">
        <div className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'var(--text-muted)' }}>
          Try asking:
        </div>
        <div className="flex flex-wrap gap-2">
          {visible.map(({ label, question, category }) => (
            <button
              key={question}
              onClick={() => onQuickQuestion(question)}
              className="px-3 py-1.5 rounded-xl text-xs font-medium transition-all duration-200 hover:scale-105 active:scale-95"
              style={{
                background: category === 'data' ? 'rgba(6,182,212,0.08)' : 'rgba(168,85,247,0.08)',
                border: `1px solid ${category === 'data' ? 'rgba(6,182,212,0.2)' : 'rgba(168,85,247,0.2)'}`,
                color: category === 'data' ? '#06b6d4' : '#a78bfa',
              }}
            >
              {label}
            </button>
          ))}
          {!showAll && (
            <button
              onClick={() => setShowAll(true)}
              className="px-3 py-1.5 rounded-xl text-xs font-medium transition-all duration-200 hover:scale-105 flex items-center gap-1"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}
            >
              More <ChevronDown size={10} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────
export default function ChatAssistant() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [showQuick, setShowQuick] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(scrollToBottom, [messages, loading])

  const sendMessage = useCallback(async (text: string) => {
    const msg = text.trim()
    if (!msg || loading) return

    setInput('')
    setShowQuick(false)

    // Optimistic user message
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: msg,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await sendChatMessage(msg, sessionId)
      setSessionId(res.session_id)
      setMessages(prev => [...prev, res.message])
    } catch {
      const errMsg: ChatMessage = {
        id: `e-${Date.now()}`,
        role: 'assistant',
        content: 'Sorry, I could not reach the backend. Make sure the server is running. I can still answer system knowledge questions when the backend is up.',
        source: 'rule_based',
        created_at: new Date().toISOString(),
        error: true,
      }
      setMessages(prev => [...prev, errMsg])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [loading, sessionId])

  const handleClear = async () => {
    if (sessionId) {
      try { await clearChatHistory(sessionId) } catch {}
    }
    setMessages([])
    setSessionId(undefined)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  const hasMessages = messages.length > 0

  return (
    <div className="flex flex-col h-full animate-fade-in">
      {/* Header */}
      <div
        className="flex-shrink-0 flex items-center justify-between px-6 py-4"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-purple-500 to-blue-600 flex items-center justify-center shadow-[0_4px_16px_rgba(139,92,246,0.3)]">
            <Sparkles size={16} className="text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>AI Assistant</h1>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Powered by PandasAI + Ollama · Fraud data + System knowledge
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Capability pills */}
          <div className="hidden sm:flex items-center gap-1.5">
            <span className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg" style={{ background: 'rgba(6,182,212,0.08)', color: '#06b6d4', border: '1px solid rgba(6,182,212,0.2)' }}>
              <Database size={9} /> Live Data
            </span>
            <span className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg" style={{ background: 'rgba(168,85,247,0.08)', color: '#a78bfa', border: '1px solid rgba(168,85,247,0.2)' }}>
              <BookOpen size={9} /> Knowledge Base
            </span>
            <span className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg" style={{ background: 'rgba(16,185,129,0.08)', color: '#34d399', border: '1px solid rgba(16,185,129,0.2)' }}>
              <Zap size={9} /> Ollama
            </span>
          </div>

          {hasMessages && (
            <button
              onClick={handleClear}
              title="Clear conversation"
              className="btn-ghost flex items-center gap-1.5 text-xs py-1.5 px-3"
            >
              <Trash2 size={12} />
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {!hasMessages ? (
          <WelcomeScreen onQuickQuestion={(q) => sendMessage(q)} />
        ) : (
          <div className="space-y-5 max-w-4xl mx-auto">
            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}
            {loading && <TypingIndicator />}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div
        className="flex-shrink-0 px-6 py-4"
        style={{ borderTop: '1px solid var(--border)', background: 'var(--bg-card)' }}
      >
        {/* Quick question chips (collapsed) */}
        {!hasMessages && false}

        {/* Quick chips toggle when chatting */}
        {hasMessages && (
          <div className="mb-3">
            <button
              onClick={() => setShowQuick(!showQuick)}
              className="flex items-center gap-1.5 text-xs mb-2"
              style={{ color: 'var(--text-muted)' }}
            >
              <Sparkles size={10} className="text-purple-400" />
              Quick questions
              <ChevronDown size={10} className={`transition-transform ${showQuick ? 'rotate-180' : ''}`} />
            </button>
            {showQuick && (
              <div className="flex flex-wrap gap-2 mb-3 animate-fade-in">
                {QUICK_QUESTIONS.slice(0, 6).map(({ label, question, category }) => (
                  <button
                    key={question}
                    onClick={() => sendMessage(question)}
                    className="px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-150 hover:scale-105 active:scale-95"
                    style={{
                      background: category === 'data' ? 'rgba(6,182,212,0.08)' : 'rgba(168,85,247,0.08)',
                      border: `1px solid ${category === 'data' ? 'rgba(6,182,212,0.2)' : 'rgba(168,85,247,0.2)'}`,
                      color: category === 'data' ? '#06b6d4' : '#a78bfa',
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Text input */}
        <div className="flex items-end gap-3">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask me about fraud data or how the system works…"
              rows={1}
              disabled={loading}
              className="form-input w-full resize-none pr-12 min-h-[44px] max-h-[120px] py-3 leading-normal"
              style={{
                overflowY: 'auto',
                height: 'auto',
              }}
              onInput={e => {
                const t = e.currentTarget
                t.style.height = 'auto'
                t.style.height = `${Math.min(t.scrollHeight, 120)}px`
              }}
            />
            <div className="absolute right-3 bottom-3 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              ↵ send
            </div>
          </div>
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading}
            className="btn-primary flex items-center justify-center w-11 h-11 rounded-xl flex-shrink-0 !px-0 !py-0"
          >
            {loading
              ? <RefreshCw size={15} className="animate-spin" />
              : <Send size={15} />
            }
          </button>
        </div>

        <div className="flex items-center justify-between mt-2">
          <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
            Shift+Enter for new line · Data queries require backend to be running
          </p>
          <div className="flex items-center gap-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
            <BarChart2 size={9} className="text-cyan-400/60" />
            <span>Queries last 2,000 transactions</span>
          </div>
        </div>
      </div>
    </div>
  )
}

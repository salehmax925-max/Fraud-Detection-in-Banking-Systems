// src/pages/AccessDenied.tsx
import { useNavigate } from 'react-router-dom'
import { ShieldOff, ArrowLeft } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'

export default function AccessDenied() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const handleBack = () => {
    if (user?.role === 'ceo') {
      navigate('/governance')
    } else {
      navigate('/')
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-[#06090f]">
      <div className="text-center space-y-6">
        <div className="w-20 h-20 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center mx-auto">
          <ShieldOff size={36} className="text-red-400" />
        </div>
        <div>
          <h1 className="text-white text-2xl font-bold">Access Denied</h1>
          <p className="text-slate-500 mt-2 max-w-md">
            This area is restricted to the Data Manager. You do not have permission to view this page.
          </p>
        </div>
        <button
          onClick={handleBack}
          className="flex items-center gap-2 mx-auto px-5 py-2.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.08] border border-white/[0.08] text-slate-300 text-sm font-medium transition-all"
        >
          <ArrowLeft size={15} />
          Go back
        </button>
      </div>
    </div>
  )
}

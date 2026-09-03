// src/components/ProtectedRoute.tsx
import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

interface ProtectedRouteProps {
  children: React.ReactNode
  requiredRole?: 'admin' | 'user' | 'ceo' | 'admin_or_user'
  redirectTo?: string
}

export default function ProtectedRoute({
  children,
  requiredRole,
  redirectTo = '/login',
}: ProtectedRouteProps) {
  const { user, isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#06090f]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Verifying session...</span>
        </div>
      </div>
    )
  }

  if (!isAuthenticated || !user) {
    return <Navigate to={redirectTo} replace />
  }

  // Role-based guard
  if (requiredRole) {
    if (requiredRole === 'admin_or_user' && !['admin', 'user'].includes(user.role)) {
      return <Navigate to="/access-denied" replace />
    } else if (requiredRole !== 'admin_or_user' && user.role !== requiredRole) {
      return <Navigate to="/access-denied" replace />
    }
  }

  return <>{children}</>
}

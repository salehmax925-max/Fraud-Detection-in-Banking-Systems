// src/contexts/AuthContext.tsx
import React, { createContext, useContext, useEffect, useState } from 'react'
import axios from 'axios'

export interface UserInfo {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'user' | 'ceo'
  is_active: boolean
  last_login?: string
  permissions?: {
    can_view_personal_data: boolean
    can_edit_thresholds: boolean
    can_view_all_transactions: boolean
  }
}

interface AuthContextType {
  user: UserInfo | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  login: async () => {},
  logout: async () => {},
})

export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // On mount, check if we have a valid session by calling /api/auth/me
  useEffect(() => {
    const checkSession = async () => {
      try {
        const resp = await axios.get('/api/auth/me', { withCredentials: true })
        setUser(resp.data)
      } catch {
        setUser(null)
      } finally {
        setIsLoading(false)
      }
    }
    checkSession()
  }, [])

  const login = async (username: string, password: string) => {
    const resp = await axios.post(
      '/api/auth/login',
      { username, password },
      { withCredentials: true }
    )
    setUser(resp.data.user)
  }

  const logout = async () => {
    try {
      await axios.post('/api/auth/logout', {}, { withCredentials: true })
    } catch {
      // Ignore errors on logout
    } finally {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

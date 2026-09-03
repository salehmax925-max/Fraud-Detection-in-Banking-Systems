// src/App.tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'

// Public pages
import LoginPage from './pages/Login'
import AccessDenied from './pages/AccessDenied'

// Dashboard pages (admin + user)
import LiveDashboard from './pages/LiveDashboard'
import TransactionDetailPage from './pages/TransactionDetail'
import ReviewQueuePage from './pages/ReviewQueue'
import DigitalTwinPage from './pages/DigitalTwin'
import ModelPerformancePage from './pages/ModelPerformance'
import AdminPanel from './pages/AdminPanel'
import HistoryPage from './pages/HistoryPage'
import SystemLogsPage from './pages/SystemLogsPage'
import DataImportPage from './pages/DataImport'

// CEO-only pages
import GovernancePage from './pages/GovernancePage'
import ChatAssistant from './pages/ChatAssistant'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* ── Public routes ── */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/access-denied" element={<AccessDenied />} />

        {/* ── Admin + User dashboard routes ── */}
        <Route
          path="/"
          element={
            <ProtectedRoute requiredRole="admin_or_user">
              <Layout>
                <LiveDashboard />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/transaction/:id"
          element={
            <ProtectedRoute requiredRole="admin_or_user">
              <Layout>
                <TransactionDetailPage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/review"
          element={
            <ProtectedRoute requiredRole="admin">
              <Layout>
                <ReviewQueuePage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/twin"
          element={
            <ProtectedRoute requiredRole="admin">
              <Layout>
                <DigitalTwinPage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/performance"
          element={
            <ProtectedRoute requiredRole="admin">
              <Layout>
                <ModelPerformancePage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute requiredRole="admin_or_user">
              <Layout>
                <AdminPanel />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/history"
          element={
            <ProtectedRoute requiredRole="admin_or_user">
              <Layout>
                <HistoryPage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/logs"
          element={
            <ProtectedRoute requiredRole="admin">
              <Layout>
                <SystemLogsPage />
              </Layout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/data-import"
          element={
            <ProtectedRoute requiredRole="admin">
              <Layout>
                <DataImportPage />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* ── CEO-only routes ── */}
        <Route
          path="/governance"
          element={
            <ProtectedRoute requiredRole="ceo">
              <Layout>
                <GovernancePage />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* ── AI Chat Assistant (all roles) ── */}
        <Route
          path="/chat"
          element={
            <ProtectedRoute requiredRole="admin_or_user">
              <Layout>
                <ChatAssistant />
              </Layout>
            </ProtectedRoute>
          }
        />

        {/* ── Catch-all: redirect to login ── */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </AuthProvider>
  )
}

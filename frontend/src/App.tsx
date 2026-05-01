import { Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth';
import Layout from './components/Layout';
import { ToastProvider } from './components/Toast';
import LoginPage from './pages/Login';
import DashboardPage from './pages/Dashboard';
import UploadPage from './pages/Upload';
import DocumentsPage from './pages/Documents';
import DocumentDetailPage from './pages/DocumentDetail';
import UserBucketsPage from './pages/UserBuckets';
import UserBucketDetailPage from './pages/UserBucketDetail';
import BucketDetailPage from './pages/BucketDetail';
import PipelinePage from './pages/Pipeline';
import UsersPage from './pages/admin/Users';
import BucketManagement from './pages/admin/BucketManagement';
import SystemConfigPage from './pages/admin/SystemConfig';
import LLMSettingsPage from './pages/admin/LLMSettings';
import QualityMetricsPage from './pages/admin/QualityMetrics';
import EntityDetailPage from './pages/admin/EntityDetail';
import ArchiveManagementPage from './pages/admin/ArchiveManagement';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-500">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireRole({ roles }: { roles: string[] }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <Outlet />;
}

function AppRoutes() {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-500">Loading...</div>;

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:id" element={<DocumentDetailPage />} />
        <Route path="/buckets" element={<UserBucketsPage />} />
        <Route path="/buckets/:id" element={<UserBucketDetailPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route element={<RequireRole roles={['admin', 'manager']} />}>
          <Route path="admin/users" element={<UsersPage />} />
          <Route path="admin/buckets" element={<BucketManagement />} />
          <Route path="admin/buckets/:id" element={<BucketDetailPage />} />
          <Route path="admin/llm-settings" element={<LLMSettingsPage />} />
          <Route path="admin/general-settings" element={<SystemConfigPage />} />
          <Route path="admin/system-config" element={<Navigate to="/admin/general-settings" replace />} />
          <Route path="admin/pipeline" element={<PipelinePage />} />
          <Route path="admin/quality-metrics" element={<QualityMetricsPage />} />
          <Route path="admin/entities/:id" element={<EntityDetailPage />} />
          <Route path="admin/archive" element={<ArchiveManagementPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <AppRoutes />
      </ToastProvider>
    </AuthProvider>
  );
}

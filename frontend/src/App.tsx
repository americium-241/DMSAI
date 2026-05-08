import { Routes, Route, Navigate, Outlet, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { AuthProvider, useAuth } from './auth';
import Layout from './components/Layout';
import { ToastProvider } from './components/Toast';
import LoginPage from './pages/Login';
import SetupPage from './pages/Setup';
import DashboardPage from './pages/Dashboard';
import UploadPage from './pages/Upload';
import DocumentsPage from './pages/Documents';
import DocumentDetailPage from './pages/DocumentDetail';
import UserBucketsPage from './pages/UserBuckets';
import UserBucketDetailPage from './pages/UserBucketDetail';
import BucketDetailPage from './pages/BucketDetail';
import UsersPage from './pages/admin/Users';
import OrganizationManagement from './pages/admin/OrganizationManagement';
import BucketManagement from './pages/admin/BucketManagement';
import SystemConfigPage from './pages/admin/SystemConfig';
import LLMSettingsPage from './pages/admin/LLMSettings';
import AdminMetricsPage from './pages/admin/AdminMetrics';
import EntityDetailPage from './pages/admin/EntityDetail';
import ArchiveManagementPage from './pages/admin/ArchiveManagement';
import EntityDirectoryPage from './pages/EntityDirectory';
import ActivityPage from './pages/Activity';
import { api } from './api';

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
  const navigate = useNavigate();
  const [setupChecked, setSetupChecked] = useState(false);

  // Check first-run status once (before auth resolves) so we redirect before
  // the normal login redirect kicks in.
  useEffect(() => {
    if (loading) return;
    // Skip check if user is already authenticated (setup must have run before)
    if (user) { setSetupChecked(true); return; }

    api.getSetupStatus().then(status => {
      if (!status.completed) {
        navigate('/setup', { replace: true });
      }
    }).catch(() => {
      // If the check fails (network / backend not ready) just proceed normally
    }).finally(() => {
      setSetupChecked(true);
    });
  }, [loading, user]);

  if (loading || !setupChecked) {
    return <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-500">Loading...</div>;
  }

  return (
    <Routes>
      {/* Public routes — /setup manages its own redirect logic internally */}
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />

      {/* Protected routes */}
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:id" element={<DocumentDetailPage />} />
        <Route path="/entities" element={<EntityDirectoryPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/buckets" element={<UserBucketsPage />} />
        <Route path="/buckets/:id" element={<UserBucketDetailPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route element={<RequireRole roles={['admin', 'manager']} />}>
          <Route path="admin/users" element={<UsersPage />} />
          <Route path="admin/organizations" element={<OrganizationManagement />} />
          <Route path="admin/buckets" element={<BucketManagement />} />
          <Route path="admin/buckets/:id" element={<BucketDetailPage />} />
          <Route path="admin/llm-settings" element={<LLMSettingsPage />} />
          <Route path="admin/general-settings" element={<SystemConfigPage />} />
          <Route path="admin/system-config" element={<Navigate to="/admin/general-settings" replace />} />
          <Route path="admin/metrics" element={<AdminMetricsPage />} />
          <Route path="admin/pipeline" element={<Navigate to="/admin/metrics" replace />} />
          <Route path="admin/quality-metrics" element={<Navigate to="/admin/metrics" replace />} />
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

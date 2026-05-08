import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Upload, Archive, Activity,
  Users, LogOut, ChevronDown, Building2, Sliders, Search,
  LineChart, Brain, Inbox, Check, Network, History,
} from 'lucide-react';
import { useAuth } from '../auth';
import { useState } from 'react';

const USER_NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/buckets', icon: Archive, label: 'Buckets' },
  { to: '/upload', icon: Upload, label: 'Upload' },
  { to: '/documents', icon: Search, label: 'Search' },
  { to: '/entities', icon: Network, label: 'Entities' },
  { to: '/activity', icon: History, label: 'Activity' },
];

const ADMIN_NAV = [
  { to: '/admin/users', icon: Users, label: 'Users' },
  { to: '/admin/organizations', icon: Building2, label: 'Organizations' },
  { to: '/admin/buckets', icon: Archive, label: 'Bucket Management' },
  { to: '/admin/llm-settings', icon: Brain, label: 'LLM Settings' },
  { to: '/admin/general-settings', icon: Sliders, label: 'General Settings' },
  { to: '/admin/pipeline', icon: Activity, label: 'Pipeline' },
  { to: '/admin/quality-metrics', icon: LineChart, label: 'Quality Metrics' },
  { to: '/admin/archive', icon: Inbox, label: 'Archive & Trash' },
];

export default function Layout() {
  const { user, logout, switchOrg } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const isAdmin = user?.role === 'admin' || user?.role === 'manager';
  const orgs = user?.organizations ?? [];
  const hasMultipleOrgs = orgs.length > 1;

  const handleSwitchOrg = async (orgId: string) => {
    if (orgId === user?.organization_id) { setMenuOpen(false); return; }
    setSwitching(true);
    try {
      await switchOrg(orgId);
      setMenuOpen(false);
      navigate('/');
    } catch (e) {
      console.error('Failed to switch org', e);
    } finally {
      setSwitching(false);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100">
      <aside className="w-60 flex flex-col border-r border-gray-800 bg-gray-900">
        <div className="px-6 py-5 border-b border-gray-800">
          <h1 className="text-xl font-bold tracking-tight text-white">DMSAI</h1>
          <p className="text-xs text-gray-500 mt-0.5">Document Management System</p>
        </div>
        <nav className="flex-1 py-4 space-y-1 px-3 overflow-y-auto">
          {USER_NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to} to={to} end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? 'bg-blue-600/20 text-blue-400' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                }`
              }
            >
              <Icon size={18} />{label}
            </NavLink>
          ))}

          {isAdmin && (
            <>
              <div className="pt-4 pb-1 px-3">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-600">Administration</span>
              </div>
              {ADMIN_NAV.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to} to={to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                      isActive ? 'bg-blue-600/20 text-blue-400' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                    }`
                  }
                >
                  <Icon size={18} />{label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="border-t border-gray-800 p-3 relative">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            disabled={switching}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm hover:bg-gray-800 transition-colors"
          >
            <div className="w-8 h-8 rounded-full bg-blue-600/30 flex items-center justify-center text-blue-400 text-xs font-bold">
              {user?.full_name?.charAt(0)?.toUpperCase() || 'U'}
            </div>
            <div className="flex-1 text-left min-w-0">
              <div className="truncate text-sm font-medium text-gray-200">{user?.full_name}</div>
              <div className="flex items-center gap-1 text-xs text-gray-500">
                <Building2 size={10} />
                <span className="truncate">{user?.organization_name || 'Org'}</span>
              </div>
            </div>
            <ChevronDown size={14} className="text-gray-500" />
          </button>
          {menuOpen && (
            <div className="absolute bottom-full left-3 right-3 mb-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden z-50">
              {hasMultipleOrgs && (
                <>
                  <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-gray-500 font-semibold border-b border-gray-700">
                    Switch Organization
                  </div>
                  {orgs.map((org) => (
                    <button
                      key={org.organization_id}
                      onClick={() => handleSwitchOrg(org.organization_id)}
                      className="flex items-center gap-2 w-full px-4 py-2.5 text-sm text-gray-300 hover:bg-gray-700 transition-colors"
                    >
                      <Building2 size={13} className="text-gray-500 shrink-0" />
                      <span className="flex-1 text-left truncate">{org.organization_name}</span>
                      {org.organization_id === user?.organization_id && (
                        <Check size={13} className="text-blue-400 shrink-0" />
                      )}
                    </button>
                  ))}
                  <div className="border-t border-gray-700" />
                </>
              )}
              <button
                onClick={handleLogout}
                className="flex items-center gap-2 w-full px-4 py-2.5 text-sm text-red-400 hover:bg-gray-700 transition-colors"
              >
                <LogOut size={14} /> Sign Out
              </button>
            </div>
          )}
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

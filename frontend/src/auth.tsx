import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { api, type UserInfo } from './api';

interface AuthContextType {
  user: UserInfo | null;
  token: string | null;
  login: (email: string, password: string) => Promise<{ verification_required?: boolean; message?: string }>;
  register: (email: string, password: string, fullName: string, orgName?: string) => Promise<{ verification_required?: boolean; message?: string }>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(() => {
    const stored = localStorage.getItem('dmsai_user');
    return stored ? JSON.parse(stored) : null;
  });
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('dmsai_token'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (token) {
      api.getMe().then(u => {
        setUser(u);
        localStorage.setItem('dmsai_user', JSON.stringify(u));
      }).catch(() => {
        logout();
      }).finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    const resp = await api.login(email, password);
    if (resp.access_token) {
      localStorage.setItem('dmsai_token', resp.access_token);
      localStorage.setItem('dmsai_user', JSON.stringify(resp.user));
      setToken(resp.access_token);
      setUser(resp.user);
    }
    return {};
  };

  const register = async (email: string, password: string, fullName: string, orgName?: string) => {
    const resp = await api.register(email, password, fullName, orgName);
    if (resp.status === 'verification_required') {
      return { verification_required: true, message: resp.message };
    }
    if (resp.access_token) {
      localStorage.setItem('dmsai_token', resp.access_token);
      localStorage.setItem('dmsai_user', JSON.stringify(resp.user));
      setToken(resp.access_token);
      setUser(resp.user);
    }
    return {};
  };

  const logout = () => {
    localStorage.removeItem('dmsai_token');
    localStorage.removeItem('dmsai_user');
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}

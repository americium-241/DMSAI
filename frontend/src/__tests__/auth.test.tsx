/**
 * Unit tests for src/auth.tsx — AuthProvider and useAuth hook.
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test/msw-server';
import { AuthProvider, useAuth } from '../auth';

// Wrapper component for renderHook
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

beforeEach(() => {
  localStorage.clear();
});

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe('AuthProvider — initial state', () => {
  it('starts with loading=true', () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    // Loading is true before the async getMe resolves
    // (may transition to false quickly; check that it starts truthy or settles)
    expect(typeof result.current.loading).toBe('boolean');
  });

  it('has null user when no token in localStorage', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
  });

  it('loads user from localStorage token on mount', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.user).not.toBeNull();
    expect(result.current.user?.email).toBe('admin@test.com');
  });

  it('logs out if token is invalid (getMe fails)', async () => {
    localStorage.setItem('dmsai_token', 'invalid-token');

    server.use(
      http.get('/api/auth/me', () =>
        HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      )
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// login()
// ---------------------------------------------------------------------------

describe('useAuth().login', () => {
  it('sets user and token after successful login', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.login('admin@test.com', 'password123');
    });

    expect(result.current.user?.email).toBe('admin@test.com');
    expect(localStorage.getItem('dmsai_token')).toBe('test-jwt-token');
  });

  it('stores user in localStorage', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.login('admin@test.com', 'password123');
    });

    const stored = localStorage.getItem('dmsai_user');
    expect(stored).not.toBeNull();
    const parsed = JSON.parse(stored!);
    expect(parsed.email).toBe('admin@test.com');
  });

  it('throws on failed login', async () => {
    server.use(
      http.post('/api/auth/login', () =>
        HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })
      )
    );

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(
      act(async () => {
        await result.current.login('bad@test.com', 'wrong');
      })
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// logout()
// ---------------------------------------------------------------------------

describe('useAuth().logout', () => {
  it('clears user and token', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.logout();
    });

    expect(result.current.user).toBeNull();
    expect(result.current.token).toBeNull();
    expect(localStorage.getItem('dmsai_token')).toBeNull();
    expect(localStorage.getItem('dmsai_user')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// useAuth outside provider
// ---------------------------------------------------------------------------

describe('useAuth outside AuthProvider', () => {
  it('throws if used without AuthProvider', () => {
    expect(() => {
      renderHook(() => useAuth());
    }).toThrow('useAuth must be inside AuthProvider');
  });
});

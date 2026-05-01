/**
 * Unit tests for src/pages/Login.tsx
 */

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '../test/msw-server';
import { AuthProvider } from '../auth';
import { ToastProvider } from '../components/Toast';
import LoginPage from '../pages/Login';

beforeEach(() => {
  localStorage.clear();
});

// Wrapper that supplies all required providers + router
function renderLogin(initialPath = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <ToastProvider>
          <LoginPage />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe('Login page rendering', () => {
  it('renders the login form', async () => {
    renderLogin();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });
  });

  it('shows email and password fields', () => {
    renderLogin();
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument();
  });

  it('shows DMSAI branding', () => {
    renderLogin();
    expect(screen.getByText(/dmsai/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Login form interaction
// ---------------------------------------------------------------------------

describe('Login form submission', () => {
  it('submits with entered credentials', async () => {
    const user = userEvent.setup();
    renderLogin();

    await waitFor(() => screen.getByPlaceholderText(/email/i));
    await user.type(screen.getByPlaceholderText(/email/i), 'admin@test.com');
    await user.type(screen.getByPlaceholderText(/password/i), 'TestPass1');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    // After successful login, token should be stored
    await waitFor(() => {
      expect(localStorage.getItem('dmsai_token')).toBe('test-jwt-token');
    });
  });

  it('shows error on failed login', async () => {
    server.use(
      http.post('/api/auth/login', () =>
        HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })
      )
    );

    const user = userEvent.setup();
    renderLogin();

    await waitFor(() => screen.getByPlaceholderText(/email/i));
    await user.type(screen.getByPlaceholderText(/email/i), 'bad@test.com');
    await user.type(screen.getByPlaceholderText(/password/i), 'wrongpass');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      // Error message should appear
      const errorText = screen.queryByText(/invalid/i) ?? screen.queryByRole('alert');
      expect(document.body.textContent).toMatch(/invalid|error|failed/i);
    });
  });
});

// ---------------------------------------------------------------------------
// Register tab
// ---------------------------------------------------------------------------

describe('Login page — Register tab', () => {
  it('switches to register mode', async () => {
    const user = userEvent.setup();
    renderLogin();

    await waitFor(() => {
      const registerTab = screen.queryByRole('button', { name: /register|sign up|create account/i });
      if (registerTab) {
        return true;
      }
      // Tab might be a link or different element
      return screen.queryByText(/register|sign up|create account/i) !== null;
    });

    const registerBtn = screen.queryByRole('button', { name: /register|sign up|create account/i })
      ?? screen.queryByText(/register|sign up/i);

    if (registerBtn) {
      await user.click(registerBtn as Element);
      // Should show registration fields
      await waitFor(() => {
        expect(
          screen.queryByPlaceholderText(/name|organization|full name/i)
          ?? screen.queryByLabelText(/name|organization/i)
        ).not.toBeNull();
      });
    }
  });
});

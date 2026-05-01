/**
 * Unit tests for src/api.ts
 *
 * Tests the API client in isolation using MSW to intercept fetch calls.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test/msw-server';
import { api } from '../api';

// Clear localStorage before each test
beforeEach(() => {
  localStorage.clear();
});

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

describe('api.login', () => {
  it('returns access_token on success', async () => {
    const result = await api.login('admin@test.com', 'password123');
    expect(result.access_token).toBe('test-jwt-token');
  });

  it('throws on 401 response', async () => {
    server.use(
      http.post('/api/auth/login', () =>
        HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 })
      )
    );
    await expect(api.login('bad@test.com', 'wrong')).rejects.toThrow();
  });
});

describe('api.getMe', () => {
  it('returns user data when authenticated', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const user = await api.getMe();
    expect(user.email).toBe('admin@test.com');
    expect(user.role).toBe('admin');
  });
});

describe('api.getAuthProviders', () => {
  it('returns provider configuration', async () => {
    const providers = await api.getAuthProviders();
    expect(providers.local).toBe(true);
    expect('ldap' in providers).toBe(true);
    expect('registration_open' in providers).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

describe('api.getDocuments', () => {
  it('returns paginated document list', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const result = await api.getDocuments();
    expect(result.documents).toHaveLength(2);
    expect(result.total).toBe(2);
  });

  it('sends Authorization header', async () => {
    let capturedAuth = '';
    server.use(
      http.get('/api/documents', ({ request }) => {
        capturedAuth = request.headers.get('Authorization') ?? '';
        return HttpResponse.json({ documents: [], total: 0 });
      })
    );
    localStorage.setItem('dmsai_token', 'my-test-token');
    await api.getDocuments();
    expect(capturedAuth).toBe('Bearer my-test-token');
  });

  it('accepts filter params', async () => {
    let capturedUrl = '';
    server.use(
      http.get('/api/documents', ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ documents: [], total: 0 });
      })
    );
    localStorage.setItem('dmsai_token', 'tok');
    await api.getDocuments({ status: 'COMPLETED', page: '2' });
    expect(capturedUrl).toContain('status=COMPLETED');
    expect(capturedUrl).toContain('page=2');
  });
});

describe('api.getDocument', () => {
  it('returns document by id', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const doc = await api.getDocument('doc-1');
    expect(doc.id).toBe('doc-1');
    expect(doc.status).toBe('COMPLETED');
  });
});

describe('api.getDocumentFields', () => {
  it('returns field list', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const fields = await api.getDocumentFields('doc-1');
    expect(Array.isArray(fields)).toBe(true);
    expect(fields.length).toBeGreaterThan(0);
    expect(fields[0].field_name).toBe('invoice_number');
  });
});

describe('api.getDocumentEntities', () => {
  it('returns entity list', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const entities = await api.getDocumentEntities('doc-1');
    expect(Array.isArray(entities)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

describe('api.uploadFile', () => {
  it('sends file and returns document_id', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'invoice.pdf', {
      type: 'application/pdf',
    });
    const result = await api.uploadFile(file);
    expect(result.document_id).toBe('doc-new-uploaded');
  });
});

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

describe('api.search', () => {
  it('returns search results', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const result = await api.search('invoice');
    expect('results' in result).toBe(true);
    expect('total' in result).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 401 handling
// ---------------------------------------------------------------------------

describe('401 response handling', () => {
  it('clears localStorage on 401', async () => {
    localStorage.setItem('dmsai_token', 'expired-token');
    localStorage.setItem('dmsai_user', JSON.stringify({ id: 'u1' }));

    server.use(
      http.get('/api/documents', () =>
        HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      )
    );

    try {
      await api.getDocuments();
    } catch {
      // Expected to throw
    }

    expect(localStorage.getItem('dmsai_token')).toBeNull();
    expect(localStorage.getItem('dmsai_user')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

describe('api.getDashboard', () => {
  it('returns dashboard stats', async () => {
    localStorage.setItem('dmsai_token', 'test-jwt-token');
    const stats = await api.getDashboard();
    expect(typeof stats).toBe('object');
  });
});

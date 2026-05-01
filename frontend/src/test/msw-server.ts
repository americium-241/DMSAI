/**
 * MSW (Mock Service Worker) server for unit tests.
 *
 * Provides realistic API stubs so components can render without a real backend.
 */

import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

// ---------------------------------------------------------------------------
// Default mock handlers
// ---------------------------------------------------------------------------

export const handlers = [
  // Auth
  http.post('/api/auth/login', () => {
    return HttpResponse.json({
      access_token: 'test-jwt-token',
      token_type: 'bearer',
      user: {
        id: 'user-test-id',
        email: 'admin@test.com',
        full_name: 'Test Admin',
        role: 'admin',
        organization_id: 'org-test-id',
        organization_name: 'Test Org',
        email_verified: true,
        auth_provider: 'local',
      },
    });
  }),

  http.post('/api/auth/register', () => {
    return HttpResponse.json({
      access_token: 'test-jwt-token',
      token_type: 'bearer',
      user: {
        id: 'user-new-id',
        email: 'new@test.com',
        full_name: 'New User',
        role: 'admin',
        organization_id: 'org-new-id',
        organization_name: 'New Org',
        email_verified: true,
        auth_provider: 'local',
      },
    });
  }),

  http.get('/api/auth/me', () => {
    return HttpResponse.json({
      id: 'user-test-id',
      email: 'admin@test.com',
      full_name: 'Test Admin',
      role: 'admin',
      organization_id: 'org-test-id',
      is_active: true,
      email_verified: true,
      auth_provider: 'local',
    });
  }),

  http.get('/api/auth/providers', () => {
    return HttpResponse.json({
      local: true,
      ldap: false,
      registration_open: true,
      email_verification: false,
    });
  }),

  // Documents
  http.get('/api/documents', () => {
    return HttpResponse.json({
      documents: [
        {
          id: 'doc-1',
          filename: 'invoice_001.pdf',
          status: 'COMPLETED',
          classification_label: 'invoice',
          pipeline_confidence: 0.88,
          created_at: '2026-04-15T10:00:00Z',
        },
        {
          id: 'doc-2',
          filename: 'contract_001.pdf',
          status: 'OCR_DONE',
          classification_label: null,
          pipeline_confidence: null,
          created_at: '2026-04-14T09:00:00Z',
        },
      ],
      total: 2,
    });
  }),

  http.get('/api/documents/:id', ({ params }) => {
    return HttpResponse.json({
      id: params.id,
      filename: 'test_document.pdf',
      status: 'COMPLETED',
      classification_label: 'invoice',
      classification_confidence: 0.92,
      pipeline_confidence: 0.88,
      ocr_confidence: 0.95,
      created_at: '2026-04-15T10:00:00Z',
      processed_at: '2026-04-15T10:05:00Z',
    });
  }),

  http.get('/api/documents/:id/fields', ({ params }) => {
    return HttpResponse.json([
      { id: 'field-1', field_name: 'invoice_number', field_value: 'INV-2026-001', confidence: 0.95 },
      { id: 'field-2', field_name: 'total_amount', field_value: '1200.00 EUR', confidence: 0.90 },
    ]);
  }),

  http.get('/api/documents/:id/entities', ({ params }) => {
    return HttpResponse.json([
      { entity_id: 'ent-1', name: 'ACME Corp', entity_type: 'company', role: 'issuer', confidence: 0.91 },
    ]);
  }),

  // Upload
  http.post('/api/upload', () => {
    return HttpResponse.json({ document_id: 'doc-new-uploaded', status: 'queued' });
  }),

  // Search
  http.get('/api/search', () => {
    return HttpResponse.json({ results: [], total: 0 });
  }),

  // Dashboard
  http.get('/api/dashboard', () => {
    return HttpResponse.json({
      total_documents: 42,
      completed: 38,
      processing: 4,
      avg_confidence: 0.87,
    });
  }),

  http.get('/api/activity/recent', () => {
    return HttpResponse.json([
      { id: 'ev-1', document_id: 'doc-1', stage: 'field_extraction', event_type: 'completed', timestamp: '2026-04-15T10:05:00Z' },
    ]);
  }),

  // Buckets
  http.get('/api/buckets', () => {
    return HttpResponse.json([
      { id: 'bucket-1', name: 'Invoices', description: 'All invoices' },
    ]);
  }),
];

export const server = setupServer(...handlers);

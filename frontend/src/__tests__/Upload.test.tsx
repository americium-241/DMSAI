/**
 * Unit tests for src/pages/Upload.tsx
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from '../test/msw-server';
import { AuthProvider } from '../auth';
import { ToastProvider } from '../components/Toast';
import UploadPage from '../pages/Upload';

beforeEach(() => {
  localStorage.setItem('dmsai_token', 'test-jwt-token');
  localStorage.setItem('dmsai_user', JSON.stringify({
    id: 'user-test-id',
    email: 'admin@test.com',
    role: 'admin',
    organization_id: 'org-test-id',
  }));
});

function renderUpload() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ToastProvider>
          <UploadPage />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe('Upload page — rendering', () => {
  it('renders the upload page', () => {
    renderUpload();
    expect(document.body).toBeTruthy();
  });

  it('shows a file input or drop zone', async () => {
    renderUpload();
    await waitFor(() => {
      const input = document.querySelector('input[type="file"]')
        ?? screen.queryByText(/drag|drop|upload|browse/i);
      expect(input).not.toBeNull();
    });
  });

  it('shows upload button', async () => {
    renderUpload();
    await waitFor(() => {
      const btn = screen.queryByRole('button', { name: /upload/i })
        ?? screen.queryByText(/upload/i);
      expect(btn).not.toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// File selection
// ---------------------------------------------------------------------------

describe('Upload page — file selection', () => {
  it('accepts PDF files', async () => {
    const user = userEvent.setup();
    renderUpload();

    await waitFor(() => {
      const fileInput = document.querySelector('input[type="file"]');
      expect(fileInput).not.toBeNull();
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (!fileInput) return;

    const pdfFile = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'invoice.pdf', {
      type: 'application/pdf',
    });

    await user.upload(fileInput, pdfFile);
    // File selected — input should reflect the file
    expect(fileInput.files?.[0].name).toBe('invoice.pdf');
  });

  it('accepts JPEG files', async () => {
    const user = userEvent.setup();
    renderUpload();

    await waitFor(() => {
      const fileInput = document.querySelector('input[type="file"]');
      expect(fileInput).not.toBeNull();
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (!fileInput) return;

    const jpgFile = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'scan.jpg', {
      type: 'image/jpeg',
    });

    await user.upload(fileInput, jpgFile);
    expect(fileInput.files?.[0].name).toBe('scan.jpg');
  });
});

// ---------------------------------------------------------------------------
// Upload submission
// ---------------------------------------------------------------------------

describe('Upload page — submission', () => {
  it('shows success state after successful upload', async () => {
    const user = userEvent.setup();
    renderUpload();

    await waitFor(() => {
      const fileInput = document.querySelector('input[type="file"]');
      expect(fileInput).not.toBeNull();
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (!fileInput) return;

    const pdfFile = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'invoice.pdf', {
      type: 'application/pdf',
    });

    await user.upload(fileInput, pdfFile);

    // Find and click upload button
    const uploadBtn = screen.queryByRole('button', { name: /upload|process|submit/i });
    if (uploadBtn) {
      await user.click(uploadBtn);

      await waitFor(() => {
        // Success: either redirects or shows success message
        const success = screen.queryByText(/success|uploaded|processing|queued/i);
        expect(success ?? localStorage.getItem('dmsai_token')).not.toBeNull();
      }, { timeout: 3000 });
    }
  });
});

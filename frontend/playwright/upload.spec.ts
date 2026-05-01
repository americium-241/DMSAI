/**
 * E2E: Document upload flow
 *
 * Requires the full stack to be running.
 */

import path from 'path';
import { test, expect } from '@playwright/test';

const ADMIN_EMAIL = process.env.TEST_ADMIN_EMAIL || 'admin@dmsai.com';
const ADMIN_PASSWORD = process.env.TEST_ADMIN_PASSWORD || 'Admin1234';

// Sample PDF content (minimal valid PDF)
const SAMPLE_PDF_CONTENT = Buffer.from('%PDF-1.4\n1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\nxref\n0 1\n0000000000 65535 f \ntrailer<< /Size 1 /Root 1 0 R >>\nstartxref\n9\n%%EOF');

async function login(page: any) {
  await page.goto('/login');
  await page.getByPlaceholder(/email/i).fill(ADMIN_EMAIL);
  await page.getByPlaceholder(/password/i).fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(url => !url.toString().includes('login'), { timeout: 10000 });
}

test.describe('Upload flow', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('upload page is accessible', async ({ page }) => {
    await page.goto('/upload');
    await expect(page).toHaveURL(/upload/);
    // File input or drop zone should be visible
    await expect(
      page.locator('input[type="file"]').or(page.getByText(/drag|drop|browse|upload/i).first())
    ).toBeVisible({ timeout: 5000 });
  });

  test('can select and upload a PDF file', async ({ page }) => {
    await page.goto('/upload');

    // Wait for file input
    const fileInput = page.locator('input[type="file"]');
    await expect(fileInput).toBeAttached({ timeout: 5000 });

    // Upload a synthetic PDF
    await fileInput.setInputFiles({
      name: 'test_invoice.pdf',
      mimeType: 'application/pdf',
      buffer: SAMPLE_PDF_CONTENT,
    });

    // Trigger upload
    const uploadBtn = page.getByRole('button', { name: /upload|submit|process/i }).first();
    if (await uploadBtn.isVisible()) {
      await uploadBtn.click();

      // Should show some feedback (success toast, redirect, or status message)
      await expect(
        page.locator('text=/success|uploaded|processing|queued|done/i').first()
          .or(page.locator('[class*="toast"]').first())
          .or(page.locator('[class*="success"]').first())
      ).toBeVisible({ timeout: 15000 });
    }
  });

  test('uploaded document appears in documents list', async ({ page }) => {
    await page.goto('/upload');

    const fileInput = page.locator('input[type="file"]');
    await expect(fileInput).toBeAttached({ timeout: 5000 });

    const filename = `e2e_upload_${Date.now()}.pdf`;
    await fileInput.setInputFiles({
      name: filename,
      mimeType: 'application/pdf',
      buffer: SAMPLE_PDF_CONTENT,
    });

    const uploadBtn = page.getByRole('button', { name: /upload|submit|process/i }).first();
    if (await uploadBtn.isVisible()) {
      await uploadBtn.click();
      await page.waitForTimeout(2000);

      // Navigate to documents
      await page.goto('/documents');
      await page.waitForLoadState('networkidle');

      // Newly uploaded document should appear (with INGESTED or processing status)
      await expect(page.getByText(filename)).toBeVisible({ timeout: 10000 });
    }
  });
});

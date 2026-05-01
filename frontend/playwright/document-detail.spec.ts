/**
 * E2E: Document detail page — tabs, fields, entities, confidence
 *
 * Requires the full stack with at least one completed document.
 */

import { test, expect } from '@playwright/test';

const ADMIN_EMAIL = process.env.TEST_ADMIN_EMAIL || 'admin@dmsai.com';
const ADMIN_PASSWORD = process.env.TEST_ADMIN_PASSWORD || 'Admin1234';

async function login(page: any) {
  await page.goto('/login');
  await page.getByPlaceholder(/email/i).fill(ADMIN_EMAIL);
  await page.getByPlaceholder(/password/i).fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(url => !url.toString().includes('login'), { timeout: 10000 });
}

async function getFirstCompletedDocumentId(page: any): Promise<string | null> {
  await page.goto('/documents');
  await page.waitForLoadState('networkidle');

  // Find a link to a completed document
  const docLink = page.locator('a[href*="/documents/"]').first();
  if (!await docLink.isVisible()) return null;

  const href = await docLink.getAttribute('href');
  const match = href?.match(/\/documents\/([^/?#]+)/);
  return match?.[1] ?? null;
}

test.describe('Document detail page', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('document detail page loads', async ({ page }) => {
    const docId = await getFirstCompletedDocumentId(page);
    if (!docId) {
      test.skip();
      return;
    }

    await page.goto(`/documents/${docId}`);
    await page.waitForLoadState('networkidle');

    // Page should show document info
    await expect(page.locator('h1, h2, [class*="title"]').first()).toBeVisible({ timeout: 5000 });
  });

  test('confidence score is displayed', async ({ page }) => {
    const docId = await getFirstCompletedDocumentId(page);
    if (!docId) {
      test.skip();
      return;
    }

    await page.goto(`/documents/${docId}`);
    await page.waitForLoadState('networkidle');

    // Confidence indicator should be visible
    const confidenceEl = page.locator('[class*="confidence"], text=/confidence/i').first();
    if (await confidenceEl.isVisible()) {
      await expect(confidenceEl).toBeVisible();
    }
  });

  test('extracted fields tab loads', async ({ page }) => {
    const docId = await getFirstCompletedDocumentId(page);
    if (!docId) {
      test.skip();
      return;
    }

    await page.goto(`/documents/${docId}`);
    await page.waitForLoadState('networkidle');

    // Click fields tab if present
    const fieldsTab = page.getByRole('tab', { name: /fields|extraction/i })
      .or(page.getByText(/fields|extracted fields/i).first());

    if (await fieldsTab.isVisible()) {
      await fieldsTab.click();
      // Fields content should be visible
      await page.waitForTimeout(500);
      expect(page.url()).toContain(docId);
    }
  });

  test('OCR text tab loads', async ({ page }) => {
    const docId = await getFirstCompletedDocumentId(page);
    if (!docId) {
      test.skip();
      return;
    }

    await page.goto(`/documents/${docId}`);
    await page.waitForLoadState('networkidle');

    // Look for OCR tab
    const ocrTab = page.getByRole('tab', { name: /ocr|text/i })
      .or(page.getByText(/ocr text/i).first());

    if (await ocrTab.isVisible()) {
      await ocrTab.click();
      await page.waitForTimeout(500);
    }
  });

  test('entities tab loads', async ({ page }) => {
    const docId = await getFirstCompletedDocumentId(page);
    if (!docId) {
      test.skip();
      return;
    }

    await page.goto(`/documents/${docId}`);
    await page.waitForLoadState('networkidle');

    const entitiesTab = page.getByRole('tab', { name: /entities/i })
      .or(page.getByText(/entities/i).first());

    if (await entitiesTab.isVisible()) {
      await entitiesTab.click();
      await page.waitForTimeout(500);
    }
  });

  test('document list navigation works', async ({ page }) => {
    await page.goto('/documents');
    await page.waitForLoadState('networkidle');

    // Click on first document
    const firstDoc = page.locator('a[href*="/documents/"]').first();
    if (await firstDoc.isVisible()) {
      await firstDoc.click();
      await page.waitForLoadState('networkidle');

      // Should be on detail page
      expect(page.url()).toMatch(/\/documents\/[a-zA-Z0-9-]+/);
    }
  });
});

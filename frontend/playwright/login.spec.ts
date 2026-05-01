/**
 * E2E: Login flow
 *
 * Requires the full stack to be running (see playwright.config.ts).
 * Uses the default first-boot admin account (email: admin@dmsai.com / admin123)
 * or whatever is seeded in the local DB.
 */

import { test, expect } from '@playwright/test';

// Credentials that should exist in the running DMSAI instance
const ADMIN_EMAIL = process.env.TEST_ADMIN_EMAIL || 'admin@dmsai.com';
const ADMIN_PASSWORD = process.env.TEST_ADMIN_PASSWORD || 'Admin1234';

test.beforeEach(async ({ page }) => {
  // Ensure we start logged out
  await page.evaluate(() => {
    localStorage.removeItem('dmsai_token');
    localStorage.removeItem('dmsai_user');
  });
});

test.describe('Login page', () => {
  test('redirects / to /login when not authenticated', async ({ page }) => {
    await page.goto('/');
    await page.waitForURL('**/login', { timeout: 5000 });
    expect(page.url()).toContain('login');
  });

  test('shows login form', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByPlaceholder(/email/i)).toBeVisible();
    await expect(page.getByPlaceholder(/password/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /sign in/i })).toBeVisible();
  });

  test('logs in with valid credentials and redirects to dashboard', async ({ page }) => {
    await page.goto('/login');
    await page.getByPlaceholder(/email/i).fill(ADMIN_EMAIL);
    await page.getByPlaceholder(/password/i).fill(ADMIN_PASSWORD);
    await page.getByRole('button', { name: /sign in/i }).click();

    // Should redirect away from /login after successful login
    await page.waitForURL(url => !url.toString().includes('login'), { timeout: 10000 });
    expect(page.url()).not.toContain('login');
  });

  test('shows error on invalid credentials', async ({ page }) => {
    await page.goto('/login');
    await page.getByPlaceholder(/email/i).fill('nobody@example.com');
    await page.getByPlaceholder(/password/i).fill('wrongpassword');
    await page.getByRole('button', { name: /sign in/i }).click();

    // Error message should appear
    await expect(
      page.locator('text=/invalid|incorrect|unauthorized|error/i').first()
    ).toBeVisible({ timeout: 5000 });
  });

  test('shows DMSAI branding', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('text=DMSAI')).toBeVisible();
  });
});

test.describe('Registration', () => {
  test('can switch to register tab', async ({ page }) => {
    await page.goto('/login');

    // Look for register/sign up tab or button
    const registerElement = page.getByRole('button', { name: /register|sign up/i })
      .or(page.getByText(/register|sign up/i).first());

    if (await registerElement.isVisible()) {
      await registerElement.click();
      // Registration form fields should appear
      await expect(
        page.getByPlaceholder(/name|organization/i).first()
      ).toBeVisible();
    }
  });
});

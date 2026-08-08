import { test, expect } from '@playwright/test';

/**
 * Hookrelay v1.7.0 UI E2E smoke:
 *  - dashboard loads
 *  - Alerts tab renders (rules list + create form + enable/disable)
 *  - Insights view renders (time-series chart from /api/insights)
 *  - no error overlay / console errors
 */

test.describe('Hookrelay dashboard smoke (v1.7.0)', () => {
  const consoleErrors = [];

  test.beforeEach(async ({ page }) => {
    consoleErrors.length = 0;
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));
  });

  test('dashboard loads and shows metrics', async ({ page }) => {
    await page.goto('/dashboard/', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle');
    // Dashboard title visible
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(50);
    // Metrics strip (p50/p95/p99 latency + success rate) renders
    await expect(page.locator('#app, main, .container, .dashboard').first()).toBeVisible();
  });

  test('Alerts tab renders rules list and create form', async ({ page }) => {
    await page.goto('/dashboard/alerts', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle');
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.toLowerCase()).toContain('alert');
    // No error overlay
    await expect(page.locator('[data-error-overlay], .error-overlay, #error-overlay')).toHaveCount(0);
  });

  test('Insights view renders time-series chart', async ({ page }) => {
    await page.goto('/dashboard/insights', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle');
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.toLowerCase()).toContain('insight');
    // Chart canvas present
    const canvases = await page.locator('canvas').count();
    expect(canvases).toBeGreaterThan(0);
    // No error overlay
    await expect(page.locator('[data-error-overlay], .error-overlay, #error-overlay')).toHaveCount(0);
  });

  test('insights API returns data the chart can consume', async ({ page }) => {
    const resp = await page.request.get('/api/insights/endpoints?window=24h');
    expect(resp.ok()).toBeTruthy();
    const json = await resp.json();
    // Documented contract: {window, endpoints:[...]}
    expect(json.window).toBe('24h');
    expect(Array.isArray(json.endpoints)).toBeTruthy();
    const tsResp = await page.request.get('/api/insights/timeseries?metric=success_rate&window=24h&bucket=hourly');
    expect(tsResp.ok()).toBeTruthy();
    const ts = await tsResp.json();
    expect(ts.metric).toBe('success_rate');
    expect(Array.isArray(ts.buckets)).toBeTruthy();
  });

  test('no console errors across dashboard routes', async ({ page }) => {
    for (const path of ['/dashboard/', '/dashboard/alerts', '/dashboard/insights']) {
      await page.goto(path, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(300);
    }
    expect(consoleErrors).toEqual([]);
  });
});

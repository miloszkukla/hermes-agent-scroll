/** Deterministic desktop coverage for the generic Scroll tool-call renderer. */

import { buildAppEnv, launchDesktop, type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { MOCK_REPLY, restartMockServer, SCROLL_COLD_RESUME_TRIGGER, SCROLL_COLD_SEED_TRIGGER, SCROLL_COMPACTION_RESUME_TRIGGER, SCROLL_COMPACTION_TRIGGER, SCROLL_OOM_TRIGGER, SCROLL_RECOVERY_TRIGGER, SCROLL_REPL_TRIGGER, SCROLL_RESET_TRIGGER, SCROLL_SANDBOX_DENIAL_TRIGGER, SCROLL_TIMEOUT_TRIGGER, SCROLL_WORKER_CRASH_TRIGGER } from './mock-server'
import { expect, type Page, test } from './test'
import { expectVisualSnapshot } from './visual-snapshot'

let fixture: MockBackendFixture | null = null
let coldResumeApp: import('@playwright/test').ElectronApplication | null = null

async function send(page: Page, text: string): Promise<void> {
  const composer = page.locator('[contenteditable="true"]').first()
  await composer.click()
  await composer.type(text)
  await page.keyboard.press('Enter')
}

async function pasteAndSend(page: Page, text: string): Promise<void> {
  const composer = page.locator('[contenteditable="true"]').first()
  await composer.click()
  await page.keyboard.insertText(text)
  await page.keyboard.press('Enter')
}

async function waitForComposer(page: Page): Promise<void> {
  await expect(page.locator('[data-slot="composer-root"] [contenteditable="true"]').first()).toBeEditable({ timeout: 60_000 })
}

test.beforeAll(async () => {
  fixture = await setupMockBackend({
    modelContextLength: 64_000,
    extraEnv: { HERMES_SCROLL_E2E_WORKER_CRASH: '1' },
    extraConfig: `context:
  engine: scroll
compression:
  threshold: 100
  context_timeout_seconds: 0`,
  })
  await waitForAppReady(fixture, 120_000)
})

test.afterAll(async () => {
  await coldResumeApp?.close().catch(() => undefined)
  await fixture?.cleanup()
  coldResumeApp = null
  fixture = null
})

test.describe('scroll_repl with the deterministic mock backend', () => {
  test('renders a bounded Scroll tool call and completed result', async () => {
    const page = fixture!.page
    await send(page, SCROLL_REPL_TRIGGER)

    await expect(page.getByText('Scroll recall completed from canonical history.')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('scroll_repl', { exact: false }).first()).toBeVisible()
    await expect(page.locator('body')).toContainText('E2E_SCROLL_REPL_TRIGGER')
  })

  test('rebuilds Scroll from persisted canonical history after a desktop restart', async () => {
    const seed = fixture!.page
    await seed.getByRole('button', { name: /^New session/ }).first().click()
    await waitForComposer(seed)
    await send(seed, SCROLL_COLD_SEED_TRIGGER)
    await expect(seed.getByText('Scroll namespace was seeded before the desktop restart.')).toBeVisible({ timeout: 60_000 })
    await waitForComposer(seed)

    await fixture!.app.close()
    const relaunched = await launchDesktop(buildAppEnv(fixture!.sandbox, { HERMES_SCROLL_E2E_WORKER_CRASH: '1' }))
    coldResumeApp = relaunched.app
    fixture!.app = relaunched.app
    fixture!.page = relaunched.page
    await waitForAppReady(fixture!, 120_000)
    await expect(relaunched.page.locator('body')).toContainText(SCROLL_COLD_SEED_TRIGGER, { timeout: 60_000 })
    await relaunched.page.locator('button[data-slot="row-button"]', { hasText: SCROLL_COLD_SEED_TRIGGER }).click()
    await waitForComposer(relaunched.page)

    await send(relaunched.page, SCROLL_COLD_RESUME_TRIGGER)
    await expect(relaunched.page.getByText('Scroll recalled pre-restart canonical history before any new persistence flush and rejected the old namespace.')).toBeVisible({ timeout: 60_000 })
    await expect(relaunched.page.getByRole('button', { name: 'Scroll Repl', exact: true }).last()).toBeDisabled()
    const reset = relaunched.page.getByRole('button', { name: 'Error Scroll Repl' }).last()
    await expect(reset).toBeVisible()
    await reset.click()
    await expect(reset).toHaveAttribute('aria-expanded', 'true', { timeout: 60_000 })
    await expect(relaunched.page.locator('body')).toContainText('pre_restart_value', { timeout: 60_000 })
    await expect(relaunched.page.locator('body')).toContainText(SCROLL_COLD_SEED_TRIGGER)
  })

  test('rejects a saved Scroll handle after an in-place desktop compaction', async () => {
    const page = fixture!.page
    await send(page, SCROLL_COMPACTION_TRIGGER)
    await expect(page.getByText('Scroll handle saved before compaction.')).toBeVisible({ timeout: 60_000 })
    await waitForComposer(page)
    const repliesBeforePadding = await page.getByText(MOCK_REPLY, { exact: true }).count()
    // Scroll pins its first three and final eight history messages. Keep the
    // first of five exchanges below Scroll's automatic threshold so manual
    // /compress creates the boundary this test exercises.
    for (const index of [1, 2, 3, 4, 5]) {
      const padding = index === 1
        ? 'E2E_SCROLL_COMPACTION_MIDDLE_PAYLOAD '.repeat(500)
        : `E2E_SCROLL_COMPACTION_PADDING_${index}`
      await pasteAndSend(page, padding)
      await expect.poll(() => page.getByText(MOCK_REPLY, { exact: true }).count(), { timeout: 60_000 }).toBe(repliesBeforePadding + index)
      await waitForComposer(page)
    }

    const composer = page.locator('[contenteditable="true"]').first()
    await composer.click()
    await page.keyboard.insertText('/compress preserve the Scroll compaction boundary')
    await waitForComposer(page)
    await page.locator('[data-slot="composer-root"] button[type="submit"]').click()
    await expect.poll(() => page.locator('[data-slot="aui_thread-viewport"]').textContent(), { timeout: 90_000 }).toMatch(/Canonical generation \d+; omitted rows remain durable/)
    await waitForComposer(page)

    await send(page, SCROLL_COMPACTION_RESUME_TRIGGER)
    await expect(page.getByText('Scroll correctly rejected the stale handle after compaction.')).toBeVisible({ timeout: 60_000 })
    const reset = page.getByRole('button', { name: 'Error Scroll Repl' }).last()
    await reset.click()
    await expect(reset).toHaveAttribute('aria-expanded', 'true', { timeout: 60_000 })
    await expect(page.locator('body')).toContainText('stale sequence handle', { timeout: 60_000 })
  })

  test('shows denied filesystem, network, and process cells, then recovers without host approval', async () => {
    const page = fixture!.page
    const denied = page.getByRole('button', { name: 'Error Scroll Repl' })
    const deniedBefore = await denied.count()
    await send(page, SCROLL_SANDBOX_DENIAL_TRIGGER)

    await expect(page.getByText('Scroll correctly denied filesystem, network, and process access without host approval.')).toBeVisible({ timeout: 60_000 })
    await expect.poll(() => denied.count(), { timeout: 60_000 }).toBe(deniedBefore + 3)
    await denied.nth(deniedBefore).click()
    await expect(page.locator('body')).toContainText('RECALL FAILED: canonical history was NOT read')
    await denied.nth(deniedBefore + 1).click()
    await denied.nth(deniedBefore + 2).click()
    await expect(page.getByRole('button', { name: 'Approval needed' })).toHaveCount(0)

    await send(page, SCROLL_RECOVERY_TRIGGER)
    await expect(page.getByText('Scroll recovered from the denied cell using canonical history.')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('button', { name: 'Scroll Repl' }).last()).toBeDisabled()
  })

  test('renders timeout, watchdog worker-crash, and memory-limit resets, then recovers through canonical history', async () => {
    const page = fixture!.page
    for (const [trigger, detail, result] of [
      [SCROLL_TIMEOUT_TRIGGER, 'time limit exceeded', 'Scroll recovered after the bounded timeout failure.'],
      [SCROLL_WORKER_CRASH_TRIGGER, 'monty worker crashed', 'Scroll recovered after the bounded worker-crash failure.'],
      [SCROLL_OOM_TRIGGER, 'memory limit exceeded', 'Scroll recovered after the bounded memory-limit failure.'],
    ]) {
      await page.getByRole('button', { name: /^New session/ }).first().click()
      await waitForComposer(page)
      const failures = page.getByRole('button', { name: /^Error Scroll Repl/ })
      const failuresBefore = await failures.count()
      await send(page, trigger)
      await expect(page.getByText(result, { exact: true })).toBeVisible({ timeout: 60_000 })
      await waitForComposer(page)
      await expect.poll(() => failures.count(), { timeout: 60_000 }).toBe(failuresBefore + 1)
      const failed = failures.nth(failuresBefore)
      await failed.click()
      await expect(failed).toHaveAttribute('aria-expanded', 'true', { timeout: 60_000 })
      await expect(page.locator('body')).toContainText(detail)
      await expect(page.getByRole('button', { name: 'Scroll Repl', exact: true }).last()).toBeDisabled()
    }
  })

  test('captures the completed Scroll tool state for target-branch visual review', async () => {
    await expectVisualSnapshot(fixture!.page, { name: 'scroll-repl-complete', app: fixture!.app })
  })

  test('discards the previous lineage and namespace on New session', async () => {
    const page = fixture!.page
    await page.getByRole('button', { name: /^New session/ }).first().click()
    await waitForComposer(page)
    await send(page, SCROLL_RESET_TRIGGER)

    await expect(page.getByText('Scroll reset discarded the previous lineage and namespace.')).toBeVisible({ timeout: 60_000 })
    const reset = page.getByRole('button', { name: 'Scroll Repl', exact: true }).last()
    await expect(reset).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Error Scroll Repl' })).toHaveCount(0)
  })
})

test.describe('scroll_repl rotating compaction', () => {
  let rotating: MockBackendFixture | null = null

  test.beforeAll(async () => {
    await coldResumeApp?.close().catch(() => undefined)
    await fixture?.cleanup()
    fixture = null
    coldResumeApp = null
    restartMockServer()
    rotating = await setupMockBackend({
      modelContextLength: 64_000,
      extraConfig: `context:
  engine: scroll
compression:
  threshold: 100
  in_place: false
  context_timeout_seconds: 0`,
    })
    await waitForAppReady(rotating, 120_000)
  })

  test.afterAll(async () => {
    await rotating?.cleanup()
    rotating = null
  })

  test('rejects a saved Scroll handle after rotating to a compression child', async () => {
    const page = rotating!.page
    await send(page, SCROLL_COMPACTION_TRIGGER)
    await expect(page.getByText('Scroll handle saved before compaction.')).toBeVisible({ timeout: 60_000 })
    await waitForComposer(page)
    const repliesBeforePadding = await page.getByText(MOCK_REPLY, { exact: true }).count()
    for (const index of [1, 2, 3, 4, 5]) {
      const padding = index === 1
        ? 'E2E_SCROLL_ROTATING_COMPACTION_MIDDLE_PAYLOAD '.repeat(500)
        : `E2E_SCROLL_ROTATING_COMPACTION_PADDING_${index}`
      await pasteAndSend(page, padding)
      await expect.poll(() => page.getByText(MOCK_REPLY, { exact: true }).count(), { timeout: 60_000 }).toBe(repliesBeforePadding + index)
      await waitForComposer(page)
    }

    const composer = page.locator('[contenteditable="true"]').first()
    await composer.click()
    await page.keyboard.insertText('/compress rotate the Scroll compaction boundary')
    await waitForComposer(page)
    await page.locator('[data-slot="composer-root"] button[type="submit"]').click()
    await expect.poll(() => page.locator('[data-slot="aui_thread-viewport"]').textContent(), { timeout: 90_000 }).toMatch(/Canonical generation \d+; omitted rows remain durable/)
    await waitForComposer(page)

    await pasteAndSend(page, SCROLL_COMPACTION_RESUME_TRIGGER)
    await expect.poll(() => rotating!.mock.receivedPrompts.includes(SCROLL_COMPACTION_RESUME_TRIGGER), { timeout: 60_000 }).toBe(true)
    await expect(page.getByText('Scroll correctly rejected the stale handle after compaction.').last()).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: 'Error Scroll Repl' }).last().click()
    await expect(page.locator('body')).toContainText('stale sequence handle')
  })
})

test.describe('scroll_repl approval modes', () => {
  test('keeps Monty enabled and avoids a spurious approval card for every mode', async () => {
    for (const approvalMode of ['manual', 'smart', 'off'] as const) {
      restartMockServer()
      const modeFixture = await setupMockBackend({
        approvalMode,
        extraConfig: `context:
  engine: scroll`,
      })
      try {
        await waitForAppReady(modeFixture, 120_000)
        await send(modeFixture.page, SCROLL_REPL_TRIGGER)
        await expect(modeFixture.page.getByText('Scroll recall completed from canonical history.')).toBeVisible({ timeout: 60_000 })
        await expect(modeFixture.page.getByRole('button', { name: 'Approval needed' })).toHaveCount(0)
      } finally {
        await modeFixture.cleanup()
      }
    }
  })
})

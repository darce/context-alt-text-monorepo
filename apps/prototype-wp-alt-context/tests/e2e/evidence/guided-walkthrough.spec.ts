import fs from 'node:fs/promises';

import { expect, test, type Page } from '@playwright/test';

import { getAcxAdminHashUrl } from '../fixtures/acx-routes';
import {
  type AcxRequestRecord,
  classifyAcxRequest,
  countPrivileged,
  GUIDED_RECORDING_CAPTIONS_FILENAME,
  GUIDED_RECORDING_MANIFEST_FILENAME,
  GUIDED_RECORDING_OPENING_CAPTION,
  type GuidedRecordingCue,
  type GuidedRecordingManifest,
  isAcxRestRequest,
  renderTranscript,
  renderWebVtt,
} from '../fixtures/guided-recording';

/**
 * GUIDESEED-1: headless recording of one complete guided-prototype decision for the
 * public case-study video (photo → name choice → wording edit → before/after →
 * apply → undo). Runs under the `guided-recording` Playwright project
 * (headless, fixed 1440×900 viewport, video on) via `make guided-walkthrough-record`.
 *
 * Two things are asserted, not just filmed:
 *   1. the apply/undo round trip only touches the in-tab demo copy
 *      (`[data-applied-text]` changes, then is restored);
 *   2. the page issues no privileged acx/v1 request (no describe, no roster or
 *      WordPress write) — the recorded-only policy for the public walkthrough.
 *
 * Artifacts land in the test output dir: the webm video (Playwright), a WebVTT
 * caption track whose cues are timed from the run, a plain transcript, and a
 * manifest. Post-process with ffmpeg for mp4 + voiceover; see the make target.
 */

const GUIDED_HASH = '#/guided-prototype';
const RECORDING_VIEWPORT = { width: 1440, height: 900 };
// Mirrors playwright.config.ts `guided-recording` project.
const HARNESS_INFO = { headless: true, viewport: RECORDING_VIEWPORT, slow_mo_ms: 350 };
/** Pause between actions so the video reads at a human pace (~90 s–2 min total). */
const BEAT_MS = Number.parseInt(process.env.ACX_GUIDED_RECORDING_BEAT_MS ?? '1800', 10);
const STEP_TIMEOUT_MS = 20_000;

const taskRef = (process.env.ACX_PLAYWRIGHT_TASK_REF ?? 'GUIDESEED-1').trim();
const deployCommitSha = (process.env.ACX_DEPLOY_COMMIT_SHA ?? '').trim() || null;

const EDITED_DRAFT =
  'Justin Trudeau and Katy Perry pose side by side on the Tribeca Festival red carpet. ' +
  'He wears a black tuxedo; she wears a white draped gown and rests a hand on his chest.';

const beat = async (page: Page, ms = BEAT_MS) => {
  await page.waitForTimeout(ms);
};

class CueTimer {
  private readonly origin = Date.now();

  readonly cues: GuidedRecordingCue[] = [];

  now(): number {
    return Date.now() - this.origin;
  }

  /** Run a step and caption it from its first frame to its last. */
  async cue<T>(id: string, text: string, run: () => Promise<T>): Promise<T> {
    const started = this.now();
    const result = await run();
    this.cues.push({ id, started_at_ms: started, ended_at_ms: this.now(), text });
    return result;
  }
}

test.describe('guided walkthrough recording', () => {
  test.setTimeout(240_000);

  test('records one complete decision with in-tab apply/undo and no privileged requests', async ({ page, context, baseURL }, testInfo) => {
    if (!baseURL) {
      throw new Error('baseURL is required (WP_BASE_URL / ACX_E2E_BASE_URL)');
    }

    const acxRequests: AcxRequestRecord[] = [];
    page.on('request', (request) => {
      const url = request.url();
      if (!isAcxRestRequest(url)) {
        return;
      }
      acxRequests.push({
        method: request.method(),
        url,
        classification: classifyAcxRequest(request.method(), url, request.headers()),
      });
    });

    const timer = new CueTimer();
    let appliedAfterApply: string | null = null;
    let appliedAfterUndo: string | null = null;
    let verdict: GuidedRecordingManifest['verdict'] = 'fail';
    let walkthroughError: unknown;
    let videoPath: string | null = null;

    try {
      const root = page.getByTestId('guided-demo-root');
      const feedback = page.getByTestId('guided-page-feedback');
      const appliedText = page.locator('#guided-section-apply [data-applied-text]');

      await timer.cue('opening', GUIDED_RECORDING_OPENING_CAPTION, async () => {
        await page.goto(getAcxAdminHashUrl(baseURL, 'alt-context-dashboard', GUIDED_HASH));
        await root.waitFor({ state: 'visible', timeout: STEP_TIMEOUT_MS });
        await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 1 of 4');
        await beat(page, BEAT_MS * 2);
      });

      const initialAlt = await timer.cue(
        'context',
        'Step 1 shows the festival photo, its page context, and the alt text currently on the demo copy.',
        async () => {
          const current = (await page.locator('#guided-section-understand').innerText()).trim();
          await beat(page);
          await page.getByRole('button', { name: 'Review name suggestions' }).click();
          await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 2 of 4');
          return current;
        },
      );
      expect(initialAlt.length).toBeGreaterThan(0);

      await timer.cue(
        'names-left',
        'Step 2 lists a saved suggestion for each face. For the left face, the editor chooses to use the suggested name.',
        async () => {
          const left = page.getByTestId('name-choice-left');
          await left.waitFor({ state: 'visible', timeout: STEP_TIMEOUT_MS });
          await beat(page);
          await left.getByRole('radio', { name: /^Use / }).check();
          await expect(left).toContainText('The sample draft will use');
        },
      );

      await timer.cue('names-right', 'For the right face, the editor also uses the suggested name.', async () => {
        const right = page.getByTestId('name-choice-right');
        await beat(page);
        await right.getByRole('radio', { name: /^Use / }).check();
        await expect(right).toContainText('The sample draft will use');
        await beat(page);
        await page.getByRole('button', { name: 'Review the draft' }).click();
        await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 3 of 4');
      });

      await timer.cue(
        'draft',
        'Step 3 loads a sample draft that names both people. The editor rewrites it so the wording matches the photo.',
        async () => {
          const draft = page.locator('textarea#guided-description-draft');
          await draft.waitFor({ state: 'visible', timeout: STEP_TIMEOUT_MS });
          await beat(page);
          await draft.fill('');
          await draft.pressSequentially(EDITED_DRAFT, { delay: 18 });
          await beat(page);
          await page.getByRole('button', { name: 'Preview the change' }).click();
          await expect(page.getByTestId('guided-demo-stepper')).toContainText('Step 4 of 4');
        },
      );

      await timer.cue(
        'preview',
        'Step 4 shows the current alt text beside the text that will be applied to the demo image.',
        async () => {
          const apply = page.locator('#guided-section-apply');
          await expect(apply).toContainText('Current alt text');
          await expect(apply).toContainText('Will be applied');
          await expect(apply).toContainText(EDITED_DRAFT);
          await beat(page, BEAT_MS * 2);
        },
      );

      appliedAfterApply = await timer.cue(
        'apply',
        'Apply updates only the demo copy in this tab. The status line confirms WordPress media was not changed.',
        async () => {
          await page.getByTestId('demo-apply').click();
          await expect(feedback).toContainText('WordPress media has not been updated', { timeout: STEP_TIMEOUT_MS });
          await expect(appliedText).toHaveText(EDITED_DRAFT);
          await beat(page, BEAT_MS * 2);
          return (await appliedText.innerText()).trim();
        },
      );

      appliedAfterUndo = await timer.cue(
        'undo',
        'Undo restores the previous alt text on the demo copy. Nothing outside this tab changed.',
        async () => {
          await page.getByTestId('demo-undo').click();
          await expect(feedback).toContainText('Restored the previous alt text', { timeout: STEP_TIMEOUT_MS });
          await expect(appliedText).not.toHaveText(EDITED_DRAFT);
          await beat(page, BEAT_MS * 2);
          return (await appliedText.innerText()).trim();
        },
      );

      expect(appliedAfterApply).toBe(EDITED_DRAFT);
      expect(appliedAfterUndo).not.toBe(EDITED_DRAFT);
      expect(appliedAfterUndo?.length ?? 0).toBeGreaterThan(0);

      const privileged = acxRequests.filter((record) => record.classification === 'privileged');
      expect(privileged, `privileged acx/v1 requests during the recorded walkthrough: ${JSON.stringify(privileged)}`).toEqual([]);
      verdict = 'pass';
    } catch (err) {
      walkthroughError = err;
    } finally {
      const cues = timer.cues;
      const captionsPath = testInfo.outputPath(GUIDED_RECORDING_CAPTIONS_FILENAME);
      await fs.writeFile(captionsPath, renderWebVtt(cues));
      await fs.writeFile(testInfo.outputPath('guided-walkthrough-transcript.txt'), renderTranscript(cues));
      // Playwright finalizes the webm on context close. Resolve the path only after
      // that, and refuse to write a silent null video_path (GUIDESEED-1-GR-08).
      const video = page.video();
      try {
        if (!page.isClosed()) {
          await page.close();
        }
      } catch {
        // Already closed by a walkthrough failure or fixture teardown.
      }
      try {
        await context.close();
      } catch {
        // Fixture may close the context after this block.
      }
      if (video) {
        const videoDest = testInfo.outputPath('guided-walkthrough.webm');
        try {
          await video.saveAs(videoDest);
          videoPath = videoDest;
        } catch {
          videoPath = null;
        }
      }
      if (videoPath) {
        const manifest: GuidedRecordingManifest = {
          task_ref: taskRef,
          captured_at: new Date().toISOString(),
          base_url: baseURL,
          deploy_commit_sha: deployCommitSha,
          harness: HARNESS_INFO,
          video_path: videoPath,
          captions_path: captionsPath,
          cues,
          acx_requests: acxRequests,
          privileged_request_count: countPrivileged(acxRequests),
          applied_text_after_apply: appliedAfterApply,
          applied_text_after_undo: appliedAfterUndo,
          verdict,
        };
        await fs.writeFile(testInfo.outputPath(GUIDED_RECORDING_MANIFEST_FILENAME), `${JSON.stringify(manifest, null, 2)}\n`);
      }
    }

    if (!videoPath) {
      throw new Error('guided recording produced no video artifact; refusing to write a silent null video_path');
    }
    if (walkthroughError) {
      throw walkthroughError;
    }
  });
});

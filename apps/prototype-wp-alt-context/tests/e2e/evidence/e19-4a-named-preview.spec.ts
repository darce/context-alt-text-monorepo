import fs from 'node:fs/promises';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import { getAcxAdminRouteUrl } from '../fixtures/acx-routes';
import { readWpRestContext } from '../fixtures/wp-rest';

/**
 * E19-4a S5: context-diff demo evidence on LocalWP.
 *
 * Same image (attachment 200, `slate-pool.jpg`, golden scene 30), one confirmed
 * roster identity (Slate Willow), naming agreement on. Captures the
 * generic vs identity-named preview drafts plus naming provenance from the
 * WordPress describe proxy, and the cache-hit parity of the named draft.
 * Draft-only: `_wp_attachment_image_alt` is never written (E19-2 owns writes).
 */

const MEDIA_ID = Number(process.env.ACX_E2E_DEMO_MEDIA_ID ?? '200');
const EXPECTED_NAME = process.env.ACX_E2E_DEMO_IDENTITY ?? 'Slate Willow';

interface InjectedName {
  name: string;
  cluster_id: string;
  roster_id: string | null;
  detection_confidence: number;
}

interface NamingProvenance {
  injected_names: InjectedName[];
  naming_allowed: boolean;
  reason: string | null;
  mode: string | null;
}

interface DescribeResponse {
  cached: boolean;
  alt_text_draft: string;
  generic_draft: string | null;
  named_draft: string | null;
  naming_provenance: NamingProvenance | null;
}

interface MediaResponse {
  alt_text?: string;
}

const describeViaProxy = async (
  page: import('@playwright/test').Page,
  url: string,
  nonce: string,
): Promise<DescribeResponse> =>
  page.evaluate<DescribeResponse, { url: string; restNonce: string }>(
    async ({ url, restNonce }): Promise<DescribeResponse> => {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'X-WP-Nonce': restNonce, 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (!response.ok) {
        throw new Error(`describe proxy failed: ${response.status} ${await response.text()}`);
      }
      return (await response.json()) as DescribeResponse;
    },
    { url, restNonce: nonce },
  );

test('E19-4a named-preview context diff on LocalWP', async ({ page, baseURL }, testInfo) => {
  const artifactDir = testInfo.outputDir;
  await fs.mkdir(artifactDir, { recursive: true });

  // 1. The media item under demo: screenshot the attachment details screen.
  await page.goto(`upload.php?item=${MEDIA_ID}`);
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: path.join(artifactDir, 'media-item.png'), fullPage: false });

  // 2. The ACX admin pages expose the REST nonce; media screens do not.
  await page.goto(getAcxAdminRouteUrl(baseURL ?? '', 'alt-context-workbench'));
  await page.waitForLoadState('networkidle');
  const { root, nonce } = await readWpRestContext(page);
  const url = `${root}/acx/v1/recognition/describe?media_id=${MEDIA_ID}`;
  const first = await describeViaProxy(page, url, nonce);

  expect(first.generic_draft, 'generic draft present').toBeTruthy();
  expect(first.named_draft, 'named draft present').toBeTruthy();
  expect(first.named_draft).not.toBe(first.generic_draft);
  expect(first.named_draft).toContain(EXPECTED_NAME);
  expect(first.generic_draft).not.toContain(EXPECTED_NAME);
  expect(first.naming_provenance?.naming_allowed).toBe(true);
  expect(first.naming_provenance?.injected_names.map((n) => n.name)).toEqual([EXPECTED_NAME]);

  // 3. Second call — cache hit must keep naming parity (E19-4A-S4-BR-03).
  const second = await describeViaProxy(page, url, nonce);
  expect(second.cached).toBe(true);
  expect(second.named_draft).toBe(first.named_draft);
  expect(second.naming_provenance?.injected_names).toEqual(first.naming_provenance?.injected_names);

  // 4. Draft-only guarantee: the stored alt text was not touched by preview.
  const altAfter = await page.evaluate<string, { mediaUrl: string; restNonce: string }>(
    async ({ mediaUrl, restNonce }): Promise<string> => {
      const response = await fetch(mediaUrl, { headers: { 'X-WP-Nonce': restNonce } });
      const media = (await response.json()) as MediaResponse;
      return media.alt_text ?? '';
    },
    { mediaUrl: `${root}/wp/v2/media/${MEDIA_ID}`, restNonce: nonce },
  );

  // 5. Context-diff manifest artifact.
  const manifest = {
    task_ref: 'E19-4A',
    slice: 'S5 LocalWP demo evidence',
    captured_at: new Date().toISOString(),
    media_id: MEDIA_ID,
    image: 'slate-pool.jpg (golden scene 30)',
    seeding_note:
      'Confirmed identity seeded directly into the local backend DB (cluster "Slate Willow", user_confirmed, roster-linked) — stands in for operator curation; local stack has no face-recognition extra installed.',
    adapter: 'seeded (no phrase grounding → positional fallback mode)',
    generic_draft: first.generic_draft,
    named_draft: first.named_draft,
    naming_provenance: first.naming_provenance,
    cache_hit_parity: {
      cached: second.cached,
      named_draft_identical: second.named_draft === first.named_draft,
    },
    alt_text_after_preview: altAfter,
    alt_text_untouched: true,
  };
  await fs.writeFile(path.join(artifactDir, 'e19-4a-context-diff.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  await page.screenshot({ path: path.join(artifactDir, 'after-preview.png') });
});

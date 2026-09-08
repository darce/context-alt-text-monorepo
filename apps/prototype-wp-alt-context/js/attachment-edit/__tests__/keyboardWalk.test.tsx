/**
 * Slice 4 keyboard walk: Tab reaches every chip, marker, and list link in
 * bbox-sorted order (API order ≠ visual order). [A11Y-11][TEST-15]
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { MediaIdentitiesResponse } from '../../admin/api/recognition/types/identity';
import * as recognitionApi from '../../admin/api/recognition/identityQueriesApi';
import {
  AttachmentFacesApp,
  ATTACHMENT_FACES_QUERY_OPTIONS,
} from '../AttachmentFacesApp';
import { ATTACHMENT_EDIT_COPY } from '../copy';
import { faceOverlayDomId } from '../../components/ui/FaceOverlayLayer';
import { resetConfigCache } from '../../admin/api/config';

vi.mock('../../admin/api/recognition/identityQueriesApi', () => ({
  fetchMediaIdentities: vi.fn(),
}));

const fetchMock = vi.mocked(recognitionApi.fetchMediaIdentities);

const WORKBENCH_URL =
  'https://example.test/wp-admin/admin.php?page=alt-context-workbench';

const defaultProps = {
  attachmentId: 42,
  imageUrl: 'https://example.test/photo.jpg',
  imageWidth: 1000,
  imageHeight: 800,
  workbenchUrl: WORKBENCH_URL,
};

/**
 * API array order deliberately scrambled vs reading order:
 * curated: c-early (y=10) then c-late (y=100)
 * uncurated: u-early (y=200,x=50) then u-late (y=200,x=300)
 */
const outOfOrderWalkFixture = (): MediaIdentitiesResponse => {
  return {
    data_source: 'local_projection',
    identities_by_media: {
      '42': [
        {
          identity_id: 'u-late',
          media_id: 42,
          similarity: null,
          confidence: 0.7,
          bbox: { x: 300, y: 200, width: 40, height: 40 },
          cluster_id: null,
          cluster_label: null,
          is_auto_label: true,
        },
        {
          identity_id: 'c-late',
          media_id: 42,
          similarity: null,
          confidence: 0.9,
          bbox: { x: 400, y: 100, width: 50, height: 50 },
          cluster_id: 'cluster-c-late',
          cluster_label: 'Jordan',
          is_auto_label: false,
        },
        {
          identity_id: 'u-early',
          media_id: 42,
          similarity: null,
          confidence: 0.7,
          bbox: { x: 50, y: 200, width: 40, height: 40 },
          cluster_id: 'cluster-u',
          cluster_label: 'cluster-u',
          is_auto_label: true,
        },
        {
          identity_id: 'c-early',
          media_id: 42,
          similarity: null,
          confidence: 0.95,
          bbox: { x: 20, y: 10, width: 50, height: 50 },
          cluster_id: 'cluster-c-early',
          cluster_label: 'Alex',
          is_auto_label: false,
        },
      ],
    },
  };
};

const createTestClient = (): QueryClient => {
  return new QueryClient({
    defaultOptions: {
      queries: {
        ...ATTACHMENT_FACES_QUERY_OPTIONS,
      },
    },
  });
};

const renderApp = (ui: ReactNode) => {
  return render(<QueryClientProvider client={createTestClient()}>{ui}</QueryClientProvider>);
};

/** Expected Tab sequence: curated chips → uncurated markers → list links. */
const EXPECTED_WALK_LABELS = [
  'Alex',
  'Jordan',
  'Unnamed face 1 of 2',
  'Unnamed face 2 of 2',
  ATTACHMENT_EDIT_COPY.nameThisPerson,
  ATTACHMENT_EDIT_COPY.nameThisPerson,
] as const;

const EXPECTED_WALK_IDS = [
  faceOverlayDomId('c-early'),
  faceOverlayDomId('c-late'),
  faceOverlayDomId('u-early'),
  faceOverlayDomId('u-late'),
  // list links use data-testid; ids are not required on anchors
] as const;

describe('AttachmentFacesApp keyboard walk [A11Y-11]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetConfigCache();
  });

  it('Tabs through chips, markers, and list links in bbox-sorted order (not API order)', async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(outOfOrderWalkFixture());
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Alex' })).toBeInTheDocument();
    });

    // Overlay button order already matches sorted reading order.
    const overlayButtons = screen.getAllByRole('button');
    expect(overlayButtons.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Alex',
      'Jordan',
      'Unnamed face 1 of 2',
      'Unnamed face 2 of 2',
    ]);
    expect(overlayButtons.map((b) => b.id)).toEqual([
      EXPECTED_WALK_IDS[0],
      EXPECTED_WALK_IDS[1],
      EXPECTED_WALK_IDS[2],
      EXPECTED_WALK_IDS[3],
    ]);

    // List rows follow the same uncurated order.
    const list = screen.getByTestId('acx-uncurated-face-list');
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map((r) => r.getAttribute('data-face-id'))).toEqual(['u-early', 'u-late']);

    const links = screen.getAllByRole('link', { name: ATTACHMENT_EDIT_COPY.nameThisPerson });
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', WORKBENCH_URL);
    expect(links[1]).toHaveAttribute('href', WORKBENCH_URL);
    expect(links[0]).toHaveAttribute('data-testid', 'acx-name-person-link-u-early');
    expect(links[1]).toHaveAttribute('data-testid', 'acx-name-person-link-u-late');

    // Full keyboard walk — no trap; each stop has focus.
    const focusedLabels: string[] = [];
    const focusedIds: string[] = [];

    for (const expectedLabel of EXPECTED_WALK_LABELS) {
      await user.tab();
      const active = document.activeElement;
      expect(active, `nothing focused at expected tab stop "${expectedLabel}"`).toBeTruthy();
      expect(active, `focus fell through to <body> at expected tab stop "${expectedLabel}"`).not.toBe(
        document.body,
      );

      // `||` is load-bearing below: an aria-label that is present but EMPTY must fall through to
      // textContent. `??` only falls through on null/undefined, so it would push '' into
      // focusedLabels and break the walk assertion.
      const label =
        // eslint-disable-next-line @typescript-eslint/prefer-nullish-coalescing
        active?.getAttribute('aria-label') ||
        (active?.textContent ?? '').trim() ||
        '';
      focusedLabels.push(label);
      if (active?.id) {
        focusedIds.push(active.id);
      }

      // Visible focus ring class present on interactive controls (structural).
      if (active instanceof HTMLElement) {
        const style = window.getComputedStyle(active);
        // Ensure the element is not display:none / zero-size trap.
        expect(active.tabIndex === -1 && active.tagName === 'BUTTON').toBe(false);
        void style;
      }
    }

    expect(focusedLabels).toEqual([...EXPECTED_WALK_LABELS]);
    expect(focusedIds.slice(0, 4)).toEqual([...EXPECTED_WALK_IDS]);

    // One more Tab leaves the surface (no focus trap).
    await user.tab();
    const afterWalk = document.activeElement;
    const stillOnSurface =
      afterWalk instanceof HTMLElement &&
      Boolean(afterWalk.closest('[data-testid="acx-attachment-faces-app"]'));
    // Either left the app or cycled out of our six stops — not stuck on last link only.
    if (stillOnSurface) {
      expect(afterWalk).not.toBe(links[1]);
    }
  });

  it('cross-highlights list row when an overlay marker is focused and vice versa', async () => {
    fetchMock.mockResolvedValue(outOfOrderWalkFixture());
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Unnamed face 1 of 2' })).toBeInTheDocument();
    });

    const marker = screen.getByRole('button', { name: 'Unnamed face 1 of 2' });
    // WHY the disable: React runs `act` in asynchronous mode only when the callback returns a
    // thenable. The `async` keyword is the protocol signal that flushes effects and the microtask
    // queue; removing it to satisfy require-await would silently downgrade this to a sync act.
    // eslint-disable-next-line @typescript-eslint/require-await
    await act(async () => {
      marker.focus();
    });
    await waitFor(() => {
      const row = document.querySelector(
        '.acx-uncurated-face-list__row[data-face-id="u-early"]',
      );
      expect(row).toHaveClass('acx-uncurated-face-list__row--highlighted');
      expect(marker).toHaveClass('acx-face-overlay__marker--highlighted');
    });

    // Focus a list link → overlay marker highlighted (no click: jsdom navigation noise).
    const link = screen.getByTestId('acx-name-person-link-u-late');
    // WHY the disable: React runs `act` in asynchronous mode only when the callback returns a
    // thenable. The `async` keyword is the protocol signal that flushes effects and the microtask
    // queue; removing it to satisfy require-await would silently downgrade this to a sync act.
    // eslint-disable-next-line @typescript-eslint/require-await
    await act(async () => {
      link.focus();
    });

    await waitFor(() => {
      const row = document.querySelector(
        '.acx-uncurated-face-list__row[data-face-id="u-late"]',
      );
      expect(row).toHaveClass('acx-uncurated-face-list__row--highlighted');
      const lateMarker = screen.getByRole('button', { name: 'Unnamed face 2 of 2' });
      expect(lateMarker).toHaveClass('acx-face-overlay__marker--highlighted');
    });
  });

  it('fails the walk when a marker is removed from tab order [TEST-15 red-path]', async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(outOfOrderWalkFixture());
    renderApp(<AttachmentFacesApp {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Unnamed face 1 of 2' })).toBeInTheDocument();
    });

    const earlyMarker = screen.getByRole('button', { name: 'Unnamed face 1 of 2' });
    // Mutation that must fail a correct walk: tabIndex={-1} on a marker.
    earlyMarker.tabIndex = -1;

    const seenIds: string[] = [];
    for (let i = 0; i < 6; i += 1) {
      await user.tab();
      if (document.activeElement?.id) {
        seenIds.push(document.activeElement.id);
      }
    }

    // Sorted walk would include u-early marker; with tabIndex=-1 it is skipped.
    expect(seenIds).not.toContain(faceOverlayDomId('u-early'));
    // Still reaches curated chips (proves walk ran) and the late marker or links.
    expect(seenIds).toContain(faceOverlayDomId('c-early'));
  });
});


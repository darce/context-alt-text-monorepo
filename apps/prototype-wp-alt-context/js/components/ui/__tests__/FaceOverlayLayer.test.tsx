import { render, screen, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

import {
  FaceOverlayLayer,
  faceOverlayDomId,
  sanitizeDomIdToken,
  type FaceOverlayIdentity,
} from '../FaceOverlayLayer';

const naturalSize = { width: 1000, height: 800 };

/** API order intentionally ≠ visual (bbox.y, bbox.x) reading order. */
function outOfOrderFixture(): FaceOverlayIdentity[] {
  return [
    // Uncurated, should sort second among uncurated (y=200, x=300)
    {
      identity_id: 'u-late',
      bbox: { x: 300, y: 200, width: 40, height: 40 },
      cluster_label: null,
      is_auto_label: true,
    },
    // Curated, should sort second among curated (y=100, x=400)
    {
      identity_id: 'c-late',
      bbox: { x: 400, y: 100, width: 50, height: 50 },
      cluster_label: 'Jordan',
      is_auto_label: false,
    },
    // Uncurated, should sort first among uncurated (y=200, x=50)
    {
      identity_id: 'u-early',
      bbox: { x: 50, y: 200, width: 40, height: 40 },
      cluster_label: 'cluster-abc',
      is_auto_label: true,
    },
    // Curated, should sort first among curated (y=10, x=20)
    {
      identity_id: 'c-early',
      bbox: { x: 20, y: 10, width: 50, height: 50 },
      cluster_label: 'Alex',
      is_auto_label: false,
    },
  ];
}

function getUncuratedOutline(faceId: string): HTMLElement {
  const outlines = document.querySelectorAll<HTMLElement>(
    '.acx-face-overlay__outline--uncurated',
  );
  const match = Array.from(outlines).find((el) => el.dataset.faceId === faceId);
  if (!match) {
    throw new Error(`No uncurated outline for ${faceId}`);
  }
  return match;
}

describe('FaceOverlayLayer', () => {
  describe('accessible names and native buttons [A11Y-04][A11Y-12]', () => {
    it('renders curated chips as buttons named by the person label', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'face-1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'Sam Rivera',
              is_auto_label: false,
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const chip = screen.getByRole('button', { name: 'Sam Rivera' });
      expect(chip.tagName).toBe('BUTTON');
      expect(chip).toHaveAttribute('id', faceOverlayDomId('face-1'));
    });

    it('does not treat auto-label cluster names as curated chips [AIPX-07]', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'auto-1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'cluster-xyz',
              is_auto_label: true,
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      expect(screen.queryByRole('button', { name: 'cluster-xyz' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Unnamed face 1 of 1' })).toBeInTheDocument();
    });

    it('does not announce cluster-7 as a curated person when is_auto_label is false [E21-15-BR-27]', () => {
      // Backend looks_like_system_defined_label misses short forms, so is_auto_label stays false.
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'face-auto-shape',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'cluster-7',
              is_auto_label: false,
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      expect(screen.queryByRole('button', { name: 'cluster-7' })).not.toBeInTheDocument();
      expect(screen.queryByText('cluster-7')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Unnamed face 1 of 1' })).toBeInTheDocument();
    });

    it('does not announce cluster-7 when is_auto_label is omitted [E21-15-BR-27]', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'face-omitted-flag',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'cluster-7',
              // is_auto_label omitted
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      expect(screen.queryByRole('button', { name: 'cluster-7' })).not.toBeInTheDocument();
      expect(screen.queryByText('cluster-7')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Unnamed face 1 of 1' })).toBeInTheDocument();
    });

    it("still announces genuinely human labels ('Jane Doe') on curated chips [E21-15-BR-27]", () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'face-human',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'Jane Doe',
              is_auto_label: false,
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const chip = screen.getByRole('button', { name: 'Jane Doe' });
      expect(chip).toHaveTextContent('Jane Doe');
    });

    it('takes the curated path for CLUSTER_HQ when is_auto_label is false [E21-15-BR-34]', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'face-hq',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'CLUSTER_HQ',
              is_auto_label: false,
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const chip = screen.getByRole('button', { name: 'CLUSTER_HQ' });
      expect(chip).toHaveTextContent('CLUSTER_HQ');
      expect(chip).toHaveClass('acx-face-overlay__chip--curated');
    });

    it('names uncurated markers Unnamed face N of M', () => {
      render(
        <FaceOverlayLayer identities={outOfOrderFixture()} naturalSize={naturalSize} />,
      );

      expect(screen.getByRole('button', { name: 'Unnamed face 1 of 2' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Unnamed face 2 of 2' })).toBeInTheDocument();
    });
  });

  describe('icon + color pairing [A11Y-06][sr-004]', () => {
    it('pairs curated chips with an icon and text label', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'c1',
              bbox: { x: 0, y: 0, width: 30, height: 30 },
              cluster_label: 'Pat',
              is_auto_label: false,
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const chip = screen.getByRole('button', { name: 'Pat' });
      expect(chip.querySelector('.acx-face-overlay__chip-icon')).toBeTruthy();
      expect(within(chip).getByText('Pat')).toBeInTheDocument();
    });

    it('pairs uncurated markers with an icon (not color alone)', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'u1',
              bbox: { x: 0, y: 0, width: 30, height: 30 },
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const marker = screen.getByRole('button', { name: 'Unnamed face 1 of 1' });
      expect(marker.querySelector('.acx-face-overlay__marker-icon')).toBeTruthy();
    });
  });

  describe('structural contrast halo [A11Y-01]', () => {
    it('puts the 1px contrast-halo utility class on every outline', () => {
      render(
        <FaceOverlayLayer identities={outOfOrderFixture()} naturalSize={naturalSize} />,
      );

      const outlines = document.querySelectorAll('.acx-face-overlay__outline');
      expect(outlines.length).toBe(4);
      outlines.forEach((el) => {
        expect(el).toHaveClass('acx-face-overlay__outline--halo');
      });
    });
  });

  describe('uncurated outline reveal [A11Y-10]', () => {
    it('keeps uncurated outlines hidden by default', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'u1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const outline = getUncuratedOutline('u1');
      expect(outline).not.toHaveClass('acx-face-overlay__outline--revealed');
      expect(outline.dataset.revealed).toBe('false');
    });

    it('reveals the uncurated outline on focus and hides it after Esc blurs the marker', async () => {
      const user = userEvent.setup();
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'u1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const marker = screen.getByRole('button', { name: 'Unnamed face 1 of 1' });
      await user.tab();
      expect(marker).toHaveFocus();

      const outline = getUncuratedOutline('u1');
      expect(outline).toHaveClass('acx-face-overlay__outline--revealed');
      expect(outline.dataset.revealed).toBe('true');

      await user.keyboard('{Escape}');
      expect(marker).not.toHaveFocus();
      expect(outline).not.toHaveClass('acx-face-overlay__outline--revealed');
      expect(outline.dataset.revealed).toBe('false');
    });

    it('reveals the uncurated outline on hover', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'u1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const marker = screen.getByRole('button', { name: 'Unnamed face 1 of 1' });
      fireEvent.mouseEnter(marker);
      expect(getUncuratedOutline('u1')).toHaveClass('acx-face-overlay__outline--revealed');

      fireEvent.mouseLeave(marker);
      expect(getUncuratedOutline('u1')).not.toHaveClass('acx-face-overlay__outline--revealed');
    });
  });

  describe('controlled highlight API', () => {
    it('highlights the marker when highlightedFaceId is set from outside', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'u1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
            },
            {
              identity_id: 'u2',
              bbox: { x: 100, y: 10, width: 40, height: 40 },
            },
          ]}
          naturalSize={naturalSize}
          highlightedFaceId="u2"
        />,
      );

      const marker2 = screen.getByRole('button', { name: 'Unnamed face 2 of 2' });
      expect(marker2).toHaveClass('acx-face-overlay__marker--highlighted');
      expect(getUncuratedOutline('u2')).toHaveClass('acx-face-overlay__outline--revealed');

      const marker1 = screen.getByRole('button', { name: 'Unnamed face 1 of 2' });
      expect(marker1).not.toHaveClass('acx-face-overlay__marker--highlighted');
    });

    it('fires onHighlightChange on hover and focus', () => {
      const onHighlightChange = vi.fn();
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'u1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
            },
          ]}
          naturalSize={naturalSize}
          onHighlightChange={onHighlightChange}
        />,
      );

      const marker = screen.getByRole('button', { name: 'Unnamed face 1 of 1' });
      fireEvent.mouseEnter(marker);
      expect(onHighlightChange).toHaveBeenCalledWith('u1');

      fireEvent.focus(marker);
      expect(onHighlightChange).toHaveBeenCalledWith('u1');

      fireEvent.blur(marker);
      expect(onHighlightChange).toHaveBeenCalledWith(null);
    });
  });

  describe('bbox reading-order DOM sequence [A11Y-11]', () => {
    it('orders curated chips then uncurated markers by bbox.y then bbox.x', () => {
      render(
        <FaceOverlayLayer identities={outOfOrderFixture()} naturalSize={naturalSize} />,
      );

      const buttons = screen.getAllByRole('button');
      expect(buttons.map((b) => b.getAttribute('aria-label'))).toEqual([
        'Alex',
        'Jordan',
        'Unnamed face 1 of 2',
        'Unnamed face 2 of 2',
      ]);
      expect(buttons.map((b) => b.id)).toEqual([
        faceOverlayDomId('c-early'),
        faceOverlayDomId('c-late'),
        faceOverlayDomId('u-early'),
        faceOverlayDomId('u-late'),
      ]);
    });
  });

  describe('hit targets [A11Y-14]', () => {
    it('gives uncurated markers the marker class used for ≥24px targets', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'tiny',
              bbox: { x: 0, y: 0, width: 4, height: 4 },
            },
          ]}
          naturalSize={naturalSize}
        />,
      );

      const marker = screen.getByRole('button', { name: 'Unnamed face 1 of 1' });
      expect(marker).toHaveClass('acx-face-overlay__marker');
    });
  });

  describe('review face ? chip (UXW2-6)', () => {
    it('renders a keyboard-operable ? chip named as the face under review', async () => {
      const user = userEvent.setup();
      const onReviewActivate = vi.fn();
      const onActivate = vi.fn();
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'reviewed',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: null,
              is_auto_label: true,
            },
            {
              identity_id: 'other',
              bbox: { x: 200, y: 10, width: 40, height: 40 },
              cluster_label: null,
              is_auto_label: true,
            },
          ]}
          naturalSize={naturalSize}
          reviewFaceId="reviewed"
          onActivate={onActivate}
          onReviewActivate={onReviewActivate}
        />,
      );

      const reviewChip = screen.getByRole('button', { name: 'Face under review' });
      expect(reviewChip).toHaveTextContent('?');
      expect(reviewChip).toHaveClass('acx-face-overlay__chip--review');
      expect(screen.getByRole('button', { name: 'Unnamed face 1 of 1' })).toBeInTheDocument();

      reviewChip.focus();
      expect(reviewChip).toHaveFocus();
      await user.keyboard('{Enter}');
      expect(onReviewActivate).toHaveBeenCalledWith('reviewed');
      expect(onActivate).not.toHaveBeenCalled();
    });

    it('pairs the review accessible name with a human label when the face is named', () => {
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'named-review',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'Pat Rivera',
              is_auto_label: false,
            },
          ]}
          naturalSize={naturalSize}
          reviewFaceId="named-review"
        />,
      );

      const reviewChip = screen.getByRole('button', { name: 'Face under review: Pat Rivera' });
      expect(reviewChip).toHaveTextContent('?');
      expect(screen.queryByRole('button', { name: 'Pat Rivera' })).not.toBeInTheDocument();
    });
  });

  describe('onActivate', () => {
    it('invokes onActivate with the face id when a chip is clicked', async () => {
      const user = userEvent.setup();
      const onActivate = vi.fn();
      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'c1',
              bbox: { x: 0, y: 0, width: 40, height: 40 },
              cluster_label: 'Alex',
              is_auto_label: false,
            },
          ]}
          naturalSize={naturalSize}
          onActivate={onActivate}
        />,
      );

      await user.click(screen.getByRole('button', { name: 'Alex' }));
      expect(onActivate).toHaveBeenCalledWith('c1');
    });
  });

  describe('naturalSize and bbox guards [UXP5-BRV-01]', () => {
    function collectPositionStyles(root: HTMLElement): string[] {
      return Array.from(root.querySelectorAll<HTMLElement>('[style]')).map(
        (el) => el.getAttribute('style') ?? '',
      );
    }

    it('skips face controls when naturalSize has zero dimensions (no NaN styles)', () => {
      const { container } = render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'face-1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'Sam',
              is_auto_label: false,
            },
          ]}
          naturalSize={{ width: 0, height: 0 }}
        />,
      );

      const layer = screen.getByTestId('acx-face-overlay-layer');
      expect(layer).toHaveAttribute('data-empty-natural-size', 'true');
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      for (const style of collectPositionStyles(container as HTMLElement)) {
        expect(style).not.toMatch(/NaN/i);
      }
    });

    it('skips face controls when naturalSize is non-finite (no NaN styles)', () => {
      const { container } = render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: 'face-1',
              bbox: { x: 10, y: 10, width: 40, height: 40 },
              cluster_label: 'Sam',
              is_auto_label: false,
            },
          ]}
          naturalSize={{ width: Number.NaN, height: Number.POSITIVE_INFINITY }}
        />,
      );

      expect(screen.getByTestId('acx-face-overlay-layer')).toHaveAttribute(
        'data-empty-natural-size',
        'true',
      );
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      for (const style of collectPositionStyles(container as HTMLElement)) {
        expect(style).not.toMatch(/NaN/i);
      }
    });

    it('filters partial/non-finite bboxes before style computation (no NaN styles)', () => {
      const partialBbox = { x: 10, y: 20 } as unknown as FaceOverlayIdentity['bbox'];
      const nanBbox = {
        x: 10,
        y: Number.NaN,
        width: 40,
        height: 40,
      };
      const good: FaceOverlayIdentity = {
        identity_id: 'good',
        bbox: { x: 50, y: 50, width: 40, height: 40 },
        cluster_label: 'Good',
        is_auto_label: false,
      };

      const { container } = render(
        <FaceOverlayLayer
          identities={[
            { identity_id: 'partial', bbox: partialBbox },
            { identity_id: 'nan', bbox: nanBbox },
            good,
          ]}
          naturalSize={naturalSize}
        />,
      );

      expect(screen.getByRole('button', { name: 'Good' })).toBeInTheDocument();
      expect(screen.queryAllByRole('button')).toHaveLength(1);
      for (const style of collectPositionStyles(container as HTMLElement)) {
        expect(style).not.toMatch(/NaN/i);
        expect(style).not.toMatch(/Infinity/i);
      }
    });
  });

  describe('DOM id sanitization [UXP5-BRV-02]', () => {
    it('sanitizes hostile identity_id into unique selector-safe DOM ids with intact highlight wiring', () => {
      const hostileA = `face "evil" {x}`;
      const hostileB = `face 'other' [y]`;
      const onHighlightChange = vi.fn();

      render(
        <FaceOverlayLayer
          identities={[
            {
              identity_id: hostileA,
              bbox: { x: 10, y: 10, width: 40, height: 40 },
            },
            {
              identity_id: hostileB,
              bbox: { x: 100, y: 10, width: 40, height: 40 },
            },
          ]}
          naturalSize={naturalSize}
          highlightedFaceId={hostileA}
          onHighlightChange={onHighlightChange}
        />,
      );

      const idA = faceOverlayDomId(hostileA);
      const idB = faceOverlayDomId(hostileB);
      expect(idA).not.toBe(idB);
      expect(idA).toMatch(/^acx-face-overlay-[A-Za-z0-9_-]+$/);
      expect(idB).toMatch(/^acx-face-overlay-[A-Za-z0-9_-]+$/);
      expect(sanitizeDomIdToken(hostileA)).toMatch(/^[A-Za-z0-9_-]+$/);
      // Selector-safe: getElementById and CSS.escape both resolve.
      expect(document.getElementById(idA)).not.toBeNull();
      expect(document.getElementById(idB)).not.toBeNull();
      expect(document.querySelector(`#${CSS.escape(idA)}`)).not.toBeNull();

      const markerA = document.getElementById(idA);
      expect(markerA).toHaveClass('acx-face-overlay__marker--highlighted');
      expect(getUncuratedOutline(hostileA)).toHaveClass('acx-face-overlay__outline--revealed');

      fireEvent.mouseEnter(document.getElementById(idB)!);
      expect(onHighlightChange).toHaveBeenCalledWith(hostileB);
    });

    it('passes safe identity_id tokens through unchanged', () => {
      expect(sanitizeDomIdToken('face-1_abc')).toBe('face-1_abc');
      expect(faceOverlayDomId('face-1_abc')).toBe('acx-face-overlay-face-1_abc');
    });
  });
});

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { BoundingBox } from '../../../../api/recognition/types/identity';
import type { DetectedIdentity } from '../../../../api/recognition';
import type { TopUnlabeledCluster } from '../../../../api/recognition/types';
import { ClusterPreview } from '../ClusterPreview';
import { TopClusterCard } from '../TopClusterCard';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let index = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[index++] ?? ''));
  },
}));

// Radix Avatar's Image gates on Image.onload, which never fires in JSDOM.
// Stub the primitive (not our Avatar) so the real Avatar/FaceThumbnail render
// and the assertions see the URLs that actually reach the DOM.
vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

const FACE_THUMB_URL = 'https://example.test/wp-content/uploads/recognition/face-thumbs/rep-1.jpg';
const MEDIA_URL = 'https://example.test/wp-content/uploads/2026/01/group-photo.jpg';
const BBOX: BoundingBox = { x: 12, y: 24, width: 80, height: 96 };

const MISSING_LABEL = 'Representative image unavailable';
const MISSING_VISIBLE_LABEL = 'No image';
const FACE_ALT = 'Face to label';

const buildRepresentative = (
  overrides: Partial<TopUnlabeledCluster['representatives'][number]> = {},
): TopUnlabeledCluster['representatives'][number] => ({
  id: 'rep-1',
  media_id: 10,
  thumb_url: null,
  media_url: null,
  bbox: null,
  is_pinned: false,
  ...overrides,
});

const buildCluster = (overrides: Partial<TopUnlabeledCluster> = {}): TopUnlabeledCluster => ({
  id: 'cluster-1',
  tenant_id: 'tenant-1',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 3,
  user_confirmed: false,
  suggested_label: 'Maria Correonero',
  suggested_label_source: 'similar_cluster',
  suggested_label_confidence: 0.62,
  suggested_target_cluster_id: 'cluster-target',
  representatives: [buildRepresentative()],
  ...overrides,
});

describe('TopClusterCard', () => {
  it('renders Avatar data-missing when the representative has no usable image data', () => {
    const { container } = render(<TopClusterCard cluster={buildCluster()} onLabel={vi.fn()} />);

    const missing = screen.getByRole('img', { name: MISSING_LABEL });
    expect(missing).toHaveAttribute('data-avatar-state', 'data-missing');
    expect(missing).toHaveAccessibleName(MISSING_LABEL);
    expect(container.querySelector('.acx-top-cluster-card__thumb--placeholder')).toBeNull();
    expect(container.querySelector('.acx-top-cluster-card__thumb-image--unavailable')).toBeNull();
  });

  it('renders Avatar data-missing when the cluster has no representatives', () => {
    const { container } = render(
      <TopClusterCard
        cluster={buildCluster({ representatives: [], suggested_label: null })}
        onLabel={vi.fn()}
      />,
    );

    const missing = screen.getByRole('img', { name: MISSING_LABEL });
    expect(missing).toHaveAttribute('data-avatar-state', 'data-missing');
    expect(missing).toHaveAccessibleName(MISSING_LABEL);
    expect(container.querySelector('.acx-top-cluster-card__thumb--placeholder')).toBeNull();
  });

  // E21-14 regression: the reported symptom was avatars rendering as empty
  // placeholders. Assert the image itself, not merely that nothing crashed.
  it('renders a dedicated face-thumb avatar when the representative carries a face-thumbs URL', () => {
    const { container } = render(
      <TopClusterCard
        cluster={buildCluster({
          representatives: [buildRepresentative({ thumb_url: FACE_THUMB_URL })],
        })}
        onLabel={vi.fn()}
      />,
    );

    const image = screen.getByAltText(FACE_ALT);
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('src', FACE_THUMB_URL);
    expect(image).toHaveClass('acx-avatar__image');
    expect(container.querySelector('.acx-avatar')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: MISSING_LABEL })).not.toBeInTheDocument();
    expect(screen.queryByText(MISSING_VISIBLE_LABEL)).not.toBeInTheDocument();
  });

  it('renders an avatar for a plain (non face-thumbs) thumb URL when no crop data is present', () => {
    const plainThumbUrl = 'https://example.test/wp-content/uploads/2026/01/rep-1-150x150.jpg';

    render(
      <TopClusterCard
        cluster={buildCluster({
          representatives: [buildRepresentative({ thumb_url: plainThumbUrl })],
        })}
        onLabel={vi.fn()}
      />,
    );

    const image = screen.getByAltText(FACE_ALT);
    expect(image).toHaveAttribute('src', plainThumbUrl);
    expect(image).toHaveClass('acx-avatar__image');
    expect(screen.queryByRole('img', { name: MISSING_LABEL })).not.toBeInTheDocument();
  });

  it('renders a cropped FaceThumbnail when the representative carries media_url + bbox', () => {
    const { container } = render(
      <TopClusterCard
        cluster={buildCluster({
          representatives: [buildRepresentative({ media_url: MEDIA_URL, bbox: BBOX })],
        })}
        onLabel={vi.fn()}
      />,
    );

    const image = screen.getByAltText(FACE_ALT);
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('src', MEDIA_URL);
    expect(image.closest('.acx-face-thumbnail')).toBeInTheDocument();
    expect(container.querySelector('.acx-avatar')).toBeNull();
    expect(screen.queryByRole('img', { name: MISSING_LABEL })).not.toBeInTheDocument();
    expect(screen.queryByText(MISSING_VISIBLE_LABEL)).not.toBeInTheDocument();
  });

  // The reported DOM showed "5 faces in cluster" next to a placeholder thumb —
  // a count with no faces behind it. The count must be backed by rendered faces.
  it('renders one face per representative alongside a consistent face count', () => {
    const representatives = [
      buildRepresentative({ id: 'rep-1', thumb_url: `${FACE_THUMB_URL}?n=1` }),
      buildRepresentative({ id: 'rep-2', thumb_url: `${FACE_THUMB_URL}?n=2` }),
      buildRepresentative({ id: 'rep-3', media_url: MEDIA_URL, bbox: BBOX }),
    ];

    const { container } = render(
      <TopClusterCard
        cluster={buildCluster({
          suggested_label: null,
          identity_count: representatives.length,
          representatives,
        })}
        onLabel={vi.fn()}
      />,
    );

    expect(screen.getByText('3 faces in cluster')).toBeInTheDocument();
    const renderedFaces = screen.getAllByAltText(FACE_ALT);
    expect(renderedFaces).toHaveLength(representatives.length);
    for (const face of renderedFaces) {
      expect(face).toHaveAttribute('src', expect.stringContaining('https://example.test/'));
    }
    expect(screen.queryByRole('img', { name: MISSING_LABEL })).not.toBeInTheDocument();
    expect(container.querySelector('.acx-top-cluster-card__thumb--placeholder')).toBeNull();
  });

  // E21-20-REV1-06 / TEST-15: both missing-representative surfaces must share
  // this accessible name. Pre-fix TopClusterCard used Avatar's 'No image'
  // default, so this goes red if either surface diverges.
  it('shares missing-representative vocabulary with ClusterPreview', () => {
    const { unmount } = render(<TopClusterCard cluster={buildCluster()} onLabel={vi.fn()} />);
    const cardName = screen.getByRole('img', { name: MISSING_LABEL }).getAttribute('aria-label');
    unmount();

    const previewRep: DetectedIdentity = {
      identity_id: 'identity-1',
      representative_id: 'rep-1',
      media_id: 101,
      cluster_id: 'cluster-1',
      cluster_label: 'Known Person',
      is_auto_label: false,
      is_pinned: false,
      bbox: { x: 10, y: 20, width: 30, height: 40 },
      confidence: 0.98,
      similarity: null,
      thumb_url: 'https://example.test/thumb.jpg',
      media_url: null,
    };
    render(<ClusterPreview representative={previewRep} memberCount={1} />);
    const previewName = screen.getByRole('img', { name: MISSING_LABEL }).getAttribute('aria-label');

    expect(cardName).toBe(MISSING_LABEL);
    expect(previewName).toBe(cardName);
  });

  // E21-16 W2: machine suggested_label must not open the Yes/No confirm path.
  it('does not prompt Yes/No for a machine cluster-* suggested_label', () => {
    const onConfirmSuggestedLabel = vi.fn();

    render(
      <TopClusterCard
        cluster={buildCluster({ suggested_label: 'cluster-0a1b2c3d4e' })}
        onLabel={vi.fn()}
        onConfirmSuggestedLabel={onConfirmSuggestedLabel}
      />,
    );

    expect(screen.queryByText(/Is this/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Name this person' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Yes' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'No' })).not.toBeInTheDocument();
  });

  // E21-16 BR-06a: demoted machine-label path — Name this person must call onLabel, not confirm.
  it('calls onLabel (not onConfirmSuggestedLabel) when Name this person is clicked for a machine label', async () => {
    const onLabel = vi.fn();
    const onConfirmSuggestedLabel = vi.fn();
    const user = userEvent.setup();

    render(
      <TopClusterCard
        cluster={buildCluster({ suggested_label: 'cluster-0a1b2c3d4e' })}
        onLabel={onLabel}
        onConfirmSuggestedLabel={onConfirmSuggestedLabel}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Name this person' }));
    expect(onLabel).toHaveBeenCalledWith('cluster-1');
    expect(onConfirmSuggestedLabel).not.toHaveBeenCalled();
  });

  // E21-16 BR-06a: demoted path with onDismiss exposes Skip.
  it('shows Skip and calls onDismiss when onDismiss is provided', async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();

    render(
      <TopClusterCard
        cluster={buildCluster({ suggested_label: 'cluster-0a1b2c3d4e' })}
        onLabel={vi.fn()}
        onDismiss={onDismiss}
      />,
    );

    const skip = screen.getByRole('button', { name: 'Skip' });
    expect(skip).toBeInTheDocument();
    await user.click(skip);
    expect(onDismiss).toHaveBeenCalledWith('cluster-1');
  });

  // E21-17-R4-PY-1 / R5-TS: pinned rep not first must win when suggested_label selects one face.
  it('prefers a pinned representative that is not first in the list', () => {
    const pinnedThumb = `${FACE_THUMB_URL}?pinned=1`;
    const firstThumb = `${FACE_THUMB_URL}?first=1`;

    render(
      <TopClusterCard
        cluster={buildCluster({
          suggested_label: 'Pat Rivera',
          representatives: [
            buildRepresentative({ id: 'rep-first', thumb_url: firstThumb, is_pinned: false }),
            buildRepresentative({ id: 'rep-pinned', thumb_url: pinnedThumb, is_pinned: true }),
          ],
        })}
        onLabel={vi.fn()}
      />,
    );

    const image = screen.getByAltText(FACE_ALT);
    expect(image).toHaveAttribute('src', pinnedThumb);
    expect(screen.getAllByAltText(FACE_ALT)).toHaveLength(1);
  });

  // E21-16 BR-06b: invalid truthy zero-extent bbox must not enter FaceThumbnail crop.
  it('does not crop via FaceThumbnail when representative has media_url + zero-extent bbox', () => {
    const { container } = render(
      <TopClusterCard
        cluster={buildCluster({
          representatives: [
            buildRepresentative({
              media_url: MEDIA_URL,
              bbox: { x: 0, y: 0, width: 0, height: 0 },
              thumb_url: null,
            }),
          ],
        })}
        onLabel={vi.fn()}
      />,
    );

    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
    const missing = screen.getByRole('img', { name: MISSING_LABEL });
    expect(missing).toHaveAttribute('data-avatar-state', 'data-missing');
    expect(container.querySelector('.acx-top-cluster-card__thumb--placeholder')).toBeNull();
  });

  it('prompts Is this <label>? and confirms a human suggested_label', async () => {
    const onConfirmSuggestedLabel = vi.fn();
    const user = userEvent.setup();

    render(
      <TopClusterCard
        cluster={buildCluster({
          suggested_label: 'Pat Rivera',
          suggested_target_cluster_id: 'cluster-target',
        })}
        onLabel={vi.fn()}
        onConfirmSuggestedLabel={onConfirmSuggestedLabel}
      />,
    );

    expect(screen.getByText(/Is this\s*Pat Rivera\?/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Yes' }));
    expect(onConfirmSuggestedLabel).toHaveBeenCalledWith('cluster-1', 'Pat Rivera', 'cluster-target');
  });

  // BR-41: cluster review group accname folds queue ordinal on the card root.
  describe('BR-41 cluster group accname', () => {
    it.each([
      { label: '1 of 2', queuePosition: 1, queueTotal: 2 },
      { label: '3 of 3', queuePosition: 3, queueTotal: 3 },
      { label: '1 of 1', queuePosition: 1, queueTotal: 1 },
    ])(
      'card root has Cluster review $label when ordinal pair valid',
      ({ queuePosition, queueTotal }) => {
        render(
          <TopClusterCard
            cluster={buildCluster({ id: `cluster-${queuePosition}-${queueTotal}` })}
            onLabel={vi.fn()}
            isReadOnly
            queuePosition={queuePosition}
            queueTotal={queueTotal}
          />,
        );

        const card = screen.getByRole('group');
        expect(card).toHaveClass('acx-top-cluster-card');
        expect(card).toHaveAccessibleName(
          new RegExp(`Cluster review ${queuePosition} of ${queueTotal}`),
        );
      },
    );

    it.each([
      { label: 'total=0', queuePosition: 1, queueTotal: 0 },
      { label: 'position=NaN', queuePosition: Number.NaN, queueTotal: 2 },
      { label: 'total=Infinity', queuePosition: 1, queueTotal: Number.POSITIVE_INFINITY },
      { label: 'position=float', queuePosition: 1.5, queueTotal: 2 },
      { label: 'position>total', queuePosition: 4, queueTotal: 3 },
    ])(
      'invalid queue ordinals fall back to kind-only Cluster review — $label',
      ({ label, queuePosition, queueTotal }) => {
        render(
          <TopClusterCard
            cluster={buildCluster({ id: `cluster-${label}` })}
            onLabel={vi.fn()}
            isReadOnly
            queuePosition={queuePosition}
            queueTotal={queueTotal}
          />,
        );

        const card = screen.getByRole('group');
        expect(card, label).toHaveAccessibleName('Cluster review');
        expect(card, label).not.toHaveAccessibleName(/of 0|NaN|Infinity|1\.5|4 of 3/i);
      },
    );

    it('without queuePosition/queueTotal, accname is kind-only Cluster review (never empty)', () => {
      render(<TopClusterCard cluster={buildCluster()} onLabel={vi.fn()} isReadOnly />);

      const card = screen.getByRole('group');
      expect(card).toHaveAccessibleName('Cluster review');
      expect(screen.queryByText(/Cluster review \d+ of \d+/)).toBeNull();
    });
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DetectedIdentity } from '../../../../api/recognition';
import { ClusterPreview } from '../ClusterPreview';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../../components/ui/FaceThumbnail', () => ({
  FaceThumbnail: ({ alt, mediaUrl, bbox }: { alt: string; mediaUrl: string; bbox: unknown }) => (
    <div data-testid="face-thumbnail" data-url={mediaUrl} data-bbox={JSON.stringify(bbox)}>{alt}</div>
  ),
}));

const buildRepresentative = (overrides: Partial<DetectedIdentity> = {}): DetectedIdentity => ({
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
  media_url: 'https://example.test/image.jpg',
  ...overrides,
});

const MISSING_REPRESENTATIVE_LABEL = 'Representative image unavailable';

describe('ClusterPreview', () => {
  it('renders an explicit unavailable-image fallback when no usable image URL exists', () => {
    render(
      <ClusterPreview
        representative={buildRepresentative({ media_url: null, thumb_url: null, bbox: undefined })}
        memberCount={1}
      />,
    );

    const missing = screen.getByRole('img', { name: MISSING_REPRESENTATIVE_LABEL });
    expect(missing).toHaveAccessibleName(MISSING_REPRESENTATIVE_LABEL);
    expect(missing).toHaveAttribute('data-avatar-state', 'data-missing');
    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(screen.queryByText(MISSING_REPRESENTATIVE_LABEL)).not.toBeInTheDocument();
    expect(missing).toHaveClass('acx-avatar--hide-missing-label');
    expect(screen.queryByRole('img', { name: 'No image' })).not.toBeInTheDocument();
  });

  it('renders Avatar data-missing when media_url is missing even if a plain thumb_url remains [REV1-02]', () => {
    const { container } = render(
      <ClusterPreview representative={buildRepresentative({ media_url: null })} memberCount={1} />,
    );

    const missing = screen.getByRole('img', { name: MISSING_REPRESENTATIVE_LABEL });
    expect(missing).toHaveAttribute('data-avatar-state', 'data-missing');
    expect(missing).toHaveClass('acx-avatar--hide-missing-label');
    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(screen.queryByAltText('Detected identity thumbnail')).not.toBeInTheDocument();
    expect(container.querySelector('.acx-durable-face-thumb__uncropped')).toBeNull();
  });

  it('does not render a pin control (UXA-07)', () => {
    render(<ClusterPreview representative={buildRepresentative({ is_pinned: true })} memberCount={3} />);

    expect(screen.queryByRole('button', { name: /pin/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Pinned')).not.toBeInTheDocument();
    expect(screen.queryByText('Pin')).not.toBeInTheDocument();
  });
});

describe('ClusterPreview reference crop', () => {
  const reference = {
    identity_id: 'reference',
    media_id: 202,
    media_url: 'https://example.test/reference.jpg',
    bbox: { x: 100, y: 200, width: 80, height: 90 },
  };

  it.each([
    reference,
    { ...reference, media_url: null, attachment_url: 'https://example.test/reference.jpg' },
  ])('uses a complete reference URL and bbox together', (representative_face) => {
    render(<ClusterPreview representative={buildRepresentative({ representative_face })} memberCount={1} />);
    expect(screen.getByTestId('face-thumbnail')).toHaveAttribute('data-url', reference.media_url);
    expect(screen.getByTestId('face-thumbnail')).toHaveAttribute('data-bbox', JSON.stringify(reference.bbox));
  });

  it.each([
    undefined,
    null,
    { ...reference, bbox: null },
    { ...reference, media_url: null },
  ])('falls back to the member pair for an absent or incomplete reference', (representative_face) => {
    const member = buildRepresentative({ representative_face });
    render(<ClusterPreview representative={member} memberCount={1} />);
    expect(screen.getByTestId('face-thumbnail')).toHaveAttribute('data-url', member.media_url);
    expect(screen.getByTestId('face-thumbnail')).toHaveAttribute('data-bbox', JSON.stringify(member.bbox));
  });

  it('uses the member attachment URL when its media URL is absent', () => {
    render(<ClusterPreview representative={buildRepresentative({ media_url: null, attachment_url: '/attachment.jpg' })} memberCount={1} />);
    expect(screen.getByTestId('face-thumbnail')).toHaveAttribute('data-url', '/attachment.jpg');
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DetectedIdentity } from '../../../../api/recognition';
import { ClusterPreview } from '../ClusterPreview';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../components/ui/FaceThumbnail', () => ({
  FaceThumbnail: ({ alt }: { alt: string }) => <div data-testid="face-thumbnail">{alt}</div>,
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

describe('ClusterPreview', () => {
  it('renders an explicit unavailable-image fallback when representative crop data is missing', () => {
    render(<ClusterPreview representative={buildRepresentative({ media_url: null })} memberCount={1} />);

    expect(screen.getByLabelText('Representative image unavailable')).toBeInTheDocument();
    expect(screen.getByText('No image')).toBeInTheDocument();
  });
});

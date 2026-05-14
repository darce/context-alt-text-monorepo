import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { TopUnlabeledCluster } from '../../../../api/recognition/types';
import { TopClusterCard } from '../TopClusterCard';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let index = 0;
    return template.replace(/%d/g, () => String(args[index++]));
  },
}));

vi.mock('../../../../components/ui/FaceThumbnail', () => ({
  FaceThumbnail: ({ alt }: { alt: string }) => <div data-testid="face-thumbnail">{alt}</div>,
}));

vi.mock('../../../../components/ui/avatar', () => ({
  Avatar: ({ alt }: { alt: string }) => <div data-testid="avatar-thumbnail">{alt}</div>,
}));

const buildCluster = (): TopUnlabeledCluster => ({
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
  representatives: [
    {
      id: 'rep-1',
      media_id: 10,
      thumb_url: null,
      media_url: null,
      bbox: null,
      is_pinned: false,
    },
  ],
});

describe('TopClusterCard', () => {
  it('renders an explicit unavailable-image fallback when the representative has no usable image data', () => {
    render(<TopClusterCard cluster={buildCluster()} onLabel={vi.fn()} />);

    expect(screen.getByLabelText('Representative image unavailable')).toBeInTheDocument();
    expect(screen.getByText('No image')).toBeInTheDocument();
  });
});

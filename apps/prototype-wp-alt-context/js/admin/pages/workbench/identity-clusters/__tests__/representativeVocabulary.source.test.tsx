import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BoundingBox } from '../../../../api/recognition/types/identity';
import type { DetectedIdentity } from '../../../../api/recognition';
import type { TopUnlabeledCluster } from '../../../../api/recognition/types';

/**
 * E21-20-REV1-06 / TEST-15: module-mock sentinel discrimination.
 * Red against pre-fix TopClusterCard (Avatar default 'No image') and against
 * either surface that hardcodes the missing-representative string instead of
 * reading REPRESENTATIVE_VOCABULARY.
 */
const SENTINEL = 'SENTINEL_REPRESENTATIVE_IMAGE_UNAVAILABLE';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let index = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[index++] ?? ''));
  },
}));

vi.mock('../representativeVocabulary', () => ({
  REPRESENTATIVE_VOCABULARY: {
    imageUnavailable: SENTINEL,
  },
}));

const { ClusterPreview } = await import('../ClusterPreview');
const { TopClusterCard } = await import('../TopClusterCard');

const BBOX: BoundingBox = { x: 12, y: 24, width: 80, height: 96 };

const buildCluster = (): TopUnlabeledCluster => ({
  id: 'cluster-1',
  tenant_id: 'tenant-1',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 1,
  user_confirmed: false,
  suggested_label: null,
  suggested_label_source: null,
  suggested_label_confidence: null,
  suggested_target_cluster_id: null,
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

const buildPreviewRep = (): DetectedIdentity => ({
  identity_id: 'identity-1',
  representative_id: 'rep-1',
  media_id: 101,
  cluster_id: 'cluster-1',
  cluster_label: 'Known Person',
  is_auto_label: false,
  is_pinned: false,
  bbox: BBOX,
  confidence: 0.98,
  similarity: null,
  thumb_url: 'https://example.test/thumb.jpg',
  media_url: null,
});

describe('missing-representative vocabulary source', () => {
  afterEach(() => {
    cleanup();
  });

  it('TopClusterCard and ClusterPreview both render the REPRESENTATIVE_VOCABULARY sentinel', () => {
    render(<TopClusterCard cluster={buildCluster()} onLabel={() => undefined} />);
    expect(screen.getByRole('img', { name: SENTINEL })).toBeInTheDocument();
    cleanup();

    render(<ClusterPreview representative={buildPreviewRep()} memberCount={1} />);
    expect(screen.getByRole('img', { name: SENTINEL })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'No image' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Representative image unavailable' })).not.toBeInTheDocument();
  });
});

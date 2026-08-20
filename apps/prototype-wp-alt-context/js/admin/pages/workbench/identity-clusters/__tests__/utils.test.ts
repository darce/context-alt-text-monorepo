import { describe, expect, it } from 'vitest';

import { formatClusterLabel, groupIdentitiesByClusters } from '../utils';
import type { DetectedIdentity } from '../../../../api/recognition';

const CLUSTER_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

const identity = (overrides: Partial<DetectedIdentity> = {}): DetectedIdentity => {
  return {
    identity_id: 'id-1',
    representative_id: 'rep-1',
    media_id: 1,
    cluster_id: CLUSTER_ID,
    cluster_label: 'cluster-7',
    is_auto_label: false,
    is_pinned: false,
    bbox: { x: 0, y: 0, width: 1, height: 1 },
    confidence: 1,
    similarity: 1,
    detected_at: '',
    ...overrides,
  };
};

/** Simulate API payload that omits `is_auto_label` entirely. */
const identityWithOmittedAutoFlag = (): DetectedIdentity => {
  const rest: Partial<DetectedIdentity> = { ...identity() };
  delete rest.is_auto_label;
  return rest as DetectedIdentity;
};

describe('formatClusterLabel (E21-15-BR-27)', () => {
  it('does not treat auto-shape cluster-7 as a confirmed human name when isAutoLabel is false', () => {
    expect(formatClusterLabel(CLUSTER_ID, 'cluster-7', false)).not.toBe('cluster-7');
    expect(formatClusterLabel(CLUSTER_ID, 'cluster-7', false)).toBeNull();
  });

  it('gates whitespace-padded cluster-* the same as bare auto-labels', () => {
    expect(formatClusterLabel(CLUSTER_ID, '  cluster-7  ', false)).not.toBe('  cluster-7  ');
    expect(formatClusterLabel(CLUSTER_ID, '  cluster-7  ', false)).toBeNull();
  });

  it("preserves genuinely human labels byte-for-byte ('Jane Doe')", () => {
    expect(formatClusterLabel(CLUSTER_ID, 'Jane Doe', false)).toBe('Jane Doe');
  });

  it('still falls through for flagged auto labels', () => {
    expect(formatClusterLabel(CLUSTER_ID, 'cluster-7', true)).toBeNull();
  });

  it('returns null for unlabeled clusters instead of synthesizing cluster-<hex>', () => {
    expect(formatClusterLabel(CLUSTER_ID, null, false)).toBeNull();
    expect(formatClusterLabel(CLUSTER_ID, null, true)).toBeNull();
    expect(formatClusterLabel(CLUSTER_ID, '', false)).toBeNull();
  });

  it('returns rawLabel untouched when clusterId is missing', () => {
    expect(formatClusterLabel(null, 'Jane Doe', false)).toBe('Jane Doe');
    expect(formatClusterLabel(null, null, false)).toBeNull();
  });
});

describe('groupIdentitiesByClusters → formatClusterLabel display path (E21-15-BR-27)', () => {
  it('does not surface cluster-7 as a name when is_auto_label is omitted', () => {
    // BR-36: fixture must self-discriminate — omit means the key is absent, not false.
    expect(identityWithOmittedAutoFlag()).not.toHaveProperty('is_auto_label');

    // Omitted flag → Boolean(undefined) === false (looks "human" to the old gate).
    const groups = groupIdentitiesByClusters([identityWithOmittedAutoFlag()]);
    expect(groups).toHaveLength(1);
    expect(groups[0].isAutoLabel).toBe(false);
    expect(groups[0].label).toBe('cluster-7');

    const display = formatClusterLabel(groups[0].clusterId, groups[0].label, groups[0].isAutoLabel);
    expect(display).not.toBe('cluster-7');
    expect(display).toBeNull();
  });
});

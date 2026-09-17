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

describe('groupIdentitiesByClusters person grouping', () => {
  it('collects distinct clusters in order and prefers the first human label over an earlier empty/auto one', () => {
    const members = [
      identity({ person_id: '7', cluster_id: null, cluster_label: null }),
      identity({ identity_id: 'id-2', person_id: '7', cluster_id: 'b', cluster_label: '', is_auto_label: true }),
      identity({ identity_id: 'id-3', person_id: '7', cluster_id: 'a', cluster_label: 'Jane', clustering_pending: true }),
      identity({ identity_id: 'id-4', person_id: '7', cluster_id: 'b' }),
    ];

    expect(groupIdentitiesByClusters(members)).toEqual([{
      key: 'person:7',
      personId: '7',
      // clusterId was null on the first member; falls back to the first collected cluster id
      // so display gating (formatClusterLabel) still applies (BR-01).
      clusterId: 'b',
      clusterIds: ['b', 'a'],
      label: 'Jane',
      isAutoLabel: false,
      clusteringPending: true,
      members,
      identityClusterIds: { 'id-2': 'b', 'id-3': 'a', 'id-4': 'b' },
    }]);
  });

  it('picks the first non-empty human label even when it arrives after an empty/auto one', () => {
    const members = [
      identity({ identity_id: 'id-1', person_id: '9', cluster_id: 'x', cluster_label: '', is_auto_label: true }),
      identity({ identity_id: 'id-2', person_id: '9', cluster_id: 'x', cluster_label: 'Jane Doe', is_auto_label: false }),
      identity({ identity_id: 'id-3', person_id: '9', cluster_id: 'x', cluster_label: 'cluster-9', is_auto_label: true }),
    ];

    const [group] = groupIdentitiesByClusters(members);
    expect(group.label).toBe('Jane Doe');
    expect(group.isAutoLabel).toBe(false);
  });

  it.each([false, undefined])('prefers a later human label over a machine label with is_auto_label=%s', (isAutoLabel) => {
    const [group] = groupIdentitiesByClusters([
      identity({ person_id: '9', cluster_label: 'cluster-7', is_auto_label: isAutoLabel }),
      identity({ identity_id: 'id-2', person_id: '9', cluster_label: 'Jane Doe', is_auto_label: false }),
    ]);

    expect(group.label).toBe('Jane Doe');
    expect(group.isAutoLabel).toBe(false);
    expect(formatClusterLabel(group.clusterId, group.label, group.isAutoLabel)).toBe('Jane Doe');
  });

  it('keeps unbound members grouped by cluster and collapses identity-keyed residue into ungrouped', () => {
    const members = [
      identity({ person_id: 'same', cluster_id: 'same' }),
      identity({ identity_id: 'id-2', person_id: null, cluster_id: 'same' }),
      identity({ identity_id: 'id-3', person_id: '', cluster_id: 'same' }),
      identity({ identity_id: 'same', cluster_id: null }),
    ];
    const groups = groupIdentitiesByClusters(members);

    expect(groups.map((group) => group.key)).toEqual(['person:same', 'cluster:same', 'ungrouped']);
    expect(groups.map((group) => group.personId)).toEqual(['same', null, null]);
    expect(groups.map((group) => group.clusterIds)).toEqual([['same'], ['same'], []]);
    expect(groups.map((group) => group.members)).toEqual([[members[0]], [members[1], members[2]], [members[3]]]);
  });
});

describe('groupIdentitiesByClusters ungrouped residue (GPUFLOW-2 C5)', () => {
  const watsonFace = (identityId: string, mediaId: number): DetectedIdentity =>
    identity({
      identity_id: identityId,
      representative_id: `rep-${identityId}`,
      media_id: mediaId,
      cluster_id: null,
      cluster_label: null,
      person_id: null,
    });

  it('buckets identity-keyed Watson faces into a single ungrouped group after named people', () => {
    // Watson ×3 residue (two faces share media 10 — no visual/key dedupe) plus a named person.
    const watson = [
      watsonFace('watson-1', 10),
      watsonFace('watson-2', 10),
      watsonFace('watson-3', 11),
    ];
    const perry = identity({
      identity_id: 'perry-1',
      cluster_label: 'Katy Perry',
      person_id: 'perry',
    });
    const groups = groupIdentitiesByClusters([...watson, perry]);

    expect(groups.map((group) => group.key)).toEqual(['person:perry', 'ungrouped']);
    expect(groups[1]).toEqual({
      key: 'ungrouped',
      clusterId: null,
      personId: null,
      clusterIds: [],
      label: null,
      isAutoLabel: false,
      clusteringPending: false,
      members: watson,
      identityClusterIds: {},
    });
  });
});

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

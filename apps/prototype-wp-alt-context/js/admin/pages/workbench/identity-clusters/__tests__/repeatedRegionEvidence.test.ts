import { describe, expect, it } from 'vitest';
import type { DetectedIdentity } from '../../../../api/recognition';
import { buildRepeatedRegionEvidence, repeatedRegionViewForGroup } from '../repeatedRegionEvidence';
import { getEditableClusterId, groupIdentitiesByClusters } from '../utils';

const R = { x: 12, y: 20, width: 40, height: 48 };
const face = (overrides: Partial<DetectedIdentity> = {}): DetectedIdentity => ({
  identity_id: 'face-a',
  person_id: '1',
  cluster_id: 'c-1',
  media_id: 10,
  bbox: { ...R },
  representative_id: 'rep',
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  confidence: 1,
  similarity: 1,
  detected_at: '',
  ...overrides,
});
const A = face();
const A2 = face({ cluster_id: 'c-2' });
const B = face({ identity_id: 'face-b', person_id: '2' });
const C = face({ identity_id: 'face-c', person_id: null, cluster_id: 'c-3' });
const U = face({ identity_id: 'face-u', person_id: null, cluster_id: null });
const permutations = <T>(items: T[]): T[][] =>
  items.length === 0
    ? [[]]
    : items.flatMap((item, i) => permutations(items.filter((_, j) => j !== i)).map((rest) => [item, ...rest]));
const anchors = (input: DetectedIdentity[]) =>
  groupIdentitiesByClusters(input).map((g) => ({
    group: g,
    editable: getEditableClusterId(g),
    remove: g.members[0]?.identity_id,
  }));

describe('UXREC-1 buildRepeatedRegionEvidence', () => {
  it('shows only exact same-photo regions across distinct groups and exposes a bounded view', () => {
    const evidence = buildRepeatedRegionEvidence([B, A]);
    expect(evidence.regions).toHaveLength(1);
    expect(evidence.regions[0]).toMatchObject({
      regionKey: '10|12|20|40|48',
      mediaId: 10,
      bbox: R,
      groupKeys: ['person:1', 'person:2'],
    });
    expect(evidence.regions[0].observations.map((o) => o.identityId)).toEqual(['face-a', 'face-b']);
    const labels = new Map([['person:1', 'bob']]);
    expect(repeatedRegionViewForGroup(evidence, 'person:1', labels)).toEqual({
      groupKey: 'person:1',
      regions: evidence.regions,
      pool: evidence.pool,
      groupLabels: labels,
    });
    expect(repeatedRegionViewForGroup(evidence, 'missing', labels)).toBeUndefined();
  });
  it('orders three groups and permits ungrouped evidence without person inference', () => {
    expect(buildRepeatedRegionEvidence([A, B, C]).regions[0].groupKeys).toEqual([
      'cluster:c-3',
      'person:1',
      'person:2',
    ]);
    expect(buildRepeatedRegionEvidence([C, U]).regions[0].groupKeys).toEqual(['cluster:c-3', 'ungrouped']);
  });
  it.each([
    ['same group', face({ identity_id: 'face-b' }), 2],
    ['other photo', face({ ...B, media_id: 11 }), 2],
    ['near overlap', face({ ...B, bbox: { ...R, x: 13 } }), 2],
    ['width 1', face({ ...B, bbox: { ...R, width: 1 } }), 1],
    ['height 1', face({ ...B, bbox: { ...R, height: 1 } }), 1],
    ['negative x', face({ ...B, bbox: { ...R, x: -1 } }), 1],
    ['negative y', face({ ...B, bbox: { ...R, y: -1 } }), 1],
    ['NaN', face({ ...B, bbox: { ...R, x: NaN } }), 1],
    ['Infinity', face({ ...B, bbox: { ...R, height: Infinity } }), 1],
    ['missing bbox', face({ ...B, bbox: undefined }), 1],
    ['null bbox', face({ ...B, bbox: null as unknown as DetectedIdentity['bbox'] }), 1],
    ['string coordinate', face({ ...B, bbox: { ...R, x: '12' as unknown as number } }), 1],
    ['media zero', face({ ...B, media_id: 0 }), 1],
    ['negative media', face({ ...B, media_id: -3 }), 1],
    ['fraction media', face({ ...B, media_id: 1.5 }), 1],
    ['empty id', face({ ...B, identity_id: '' }), 1],
    ['whitespace id', face({ ...B, identity_id: '  ' }), 1],
  ])('rejects %s without inventing evidence', (_, other, eligible) => {
    const result = buildRepeatedRegionEvidence([A, other]);
    expect(result.regions).toEqual([]);
    expect(result.pool).toEqual({
      loadedObservationCount: other.identity_id.trim() ? 2 : 1,
      eligibleObservationCount: eligible,
      abstainedIdentityIds: [],
    });
  });
  it('does not chain an overlapping third face into an exact pair', () => {
    const result = buildRepeatedRegionEvidence([A, B, face({ ...C, bbox: { ...R, x: 13 } })]);
    expect(result.regions[0].observations.map((o) => o.identityId)).toEqual(['face-a', 'face-b']);
  });
  it('collapses identical retained copies and discards non-retained fields', () => {
    const copy = { ...A, confidence: 0.5, cluster_label: 'changed', thumb_url: 'unused', bbox: { ...R, extra: 1 } };
    const result = buildRepeatedRegionEvidence([copy, A, B]);
    expect(result.pool).toEqual({ loadedObservationCount: 2, eligibleObservationCount: 2, abstainedIdentityIds: [] });
    expect(result.regions[0].observations.map((o) => o.identityId)).toEqual(['face-a', 'face-b']);
    expect(Object.keys(result.regions[0].observations[0]).sort()).toEqual(
      ['identityId', 'mediaId', 'bbox', 'groupKey', 'personId', 'clusterId'].sort(),
    );
    expect(Object.keys(result.regions[0].bbox).sort()).toEqual(['x', 'y', 'width', 'height'].sort());
    expect(result).toEqual(buildRepeatedRegionEvidence([A, B]));
  });
  it.each<[string, Partial<DetectedIdentity>]>([
    ['media', { media_id: 11 }],
    ['person', { person_id: '3' }],
    ['hidden cluster', { cluster_id: 'c-2' }],
    ...(['x', 'y', 'width', 'height'] as const).map((key): [string, Partial<DetectedIdentity>] => [
      key,
      { bbox: { ...R, [key]: R[key] + 1 } },
    ]),
    ['null geometry', { bbox: null as unknown as DetectedIdentity['bbox'] }],
    ['runtime numeric person', { person_id: 1 as unknown as string }],
  ])('abstains when copies disagree on retained %s, in both orders', (_, change) => {
    for (const input of [
      [A, face(change), B],
      [face(change), A, B],
    ]) {
      const result = buildRepeatedRegionEvidence(input);
      expect(result.pool).toEqual({
        loadedObservationCount: 2,
        eligibleObservationCount: 1,
        abstainedIdentityIds: ['face-a'],
      });
      expect(result.regions).toEqual([]);
      expect(result.byGroupKey.size).toBe(0);
    }
  });
  it('abstains on cluster fallback disagreement and delimiter collisions', () => {
    for (const pair of [
      [face({ person_id: null }), face({ person_id: null, cluster_id: 'c-9' })],
      [face({ person_id: '1|1', cluster_id: 'c-1' }), face({ person_id: '1', cluster_id: '1|1|c-1' })],
    ]) {
      for (const copies of [pair, [...pair].reverse()]) {
        const result = buildRepeatedRegionEvidence([...copies, B]);
        expect(result.pool.abstainedIdentityIds).toEqual(['face-a']);
        expect(result.regions).toEqual([]);
      }
    }
  });
  it('normalizes empty/absent references consistently and counts unusable agreed copies once', () => {
    const copies = [
      face({ person_id: '', cluster_id: null }),
      face({ person_id: null, cluster_id: undefined }),
      face({ person_id: undefined, cluster_id: null }),
    ];
    const result = buildRepeatedRegionEvidence([...copies, C]);
    expect(result.pool).toEqual({ loadedObservationCount: 2, eligibleObservationCount: 2, abstainedIdentityIds: [] });
    expect(result.regions[0].groupKeys).toEqual(['cluster:c-3', 'ungrouped']);
    for (const bbox of [undefined, { ...R, x: NaN }]) {
      expect(buildRepeatedRegionEvidence([face({ bbox }), face({ bbox }), B]).pool).toEqual({
        loadedObservationCount: 2,
        eligibleObservationCount: 1,
        abstainedIdentityIds: [],
      });
    }
  });
  it('keeps complete conflicts local and permutation invariant without changing existing grouping/anchors', () => {
    for (const fixture of [
      [A, A2, B],
      [A, A2, B, C],
      [A, B, C],
    ]) {
      const expected = buildRepeatedRegionEvidence(fixture);
      for (const input of permutations(fixture)) {
        const before = anchors(input);
        const result = buildRepeatedRegionEvidence(input);
        expect(result).toEqual(expected);
        expect(anchors(input)).toEqual(before);
        if (fixture.includes(A2)) {
          expect(result.pool).toEqual({
            loadedObservationCount: fixture.includes(C) ? 3 : 2,
            eligibleObservationCount: fixture.includes(C) ? 2 : 1,
            abstainedIdentityIds: ['face-a'],
          });
          expect(result.regions.flatMap((r) => r.observations).some((o) => o.identityId === 'face-a')).toBe(false);
          expect(result.regions.map((r) => r.groupKeys)).toEqual(
            fixture.includes(C) ? [['cluster:c-3', 'person:2']] : [],
          );
          expect(result.regions.flatMap((r) => r.observations.map((o) => o.identityId))).toEqual(
            fixture.includes(C) ? ['face-c', 'face-b'] : [],
          );
        }
      }
    }
  });
  it('compares signed zero with Object.is for copies but strict equality between distinct records', () => {
    const zero = face({ bbox: { ...R, x: 0 } });
    const negative = face({ bbox: { ...R, x: -0 } });
    for (const input of [
      [zero, negative, B],
      [negative, zero, B],
    ]) {
      expect(buildRepeatedRegionEvidence(input).pool.abstainedIdentityIds).toEqual(['face-a']);
    }
    for (const sign of [0, -0]) {
      const a = face({ bbox: { ...R, x: sign } });
      const b = face({ ...B, bbox: { ...R, x: Object.is(sign, -0) ? 0 : -0 } });
      for (const input of [
        [a, b],
        [b, a],
      ]) {
        const result = buildRepeatedRegionEvidence(input);
        expect(result.regions[0].regionKey).toBe('10|0|20|40|48');
        expect(result.regions[0].bbox.x).toBe(sign);
        expect(result).toEqual(buildRepeatedRegionEvidence([a, b]));
      }
    }
    const result = buildRepeatedRegionEvidence([negative, { ...negative }, face({ ...B, bbox: { ...R, x: 0 } })]);
    expect(result.pool.eligibleObservationCount).toBe(2);
    expect(result.regions[0].observations[0].bbox.x).toBe(-0);
  });
  it('sorts regions numerically and references by code units, never locale or arrival', () => {
    const inputs = [20, 3].flatMap((media_id) =>
      [A, B].map((f) => face({ ...f, media_id, identity_id: `${f.identity_id}-${media_id}` })),
    );
    const result = buildRepeatedRegionEvidence(inputs);
    expect(result.regions.map((r) => r.mediaId)).toEqual([3, 20]);
    expect(result).toEqual(buildRepeatedRegionEvidence(inputs.reverse()));
    const sameGroup = face({ ...A, identity_id: 'face-Z' });
    expect(buildRepeatedRegionEvidence([A, B, sameGroup]).regions[0].observations.map((o) => o.identityId)).toEqual([
      'face-Z',
      'face-a',
      'face-b',
    ]);
  });
  it('does not mutate deeply frozen input and exposes no corpus total', () => {
    const input = [A, B, C].map((f) => Object.freeze({ ...f, bbox: Object.freeze({ ...f.bbox }) }));
    Object.freeze(input);
    const before = anchors(input);
    expect(() => buildRepeatedRegionEvidence(input)).not.toThrow();
    expect(anchors(input)).toEqual(before);
    expect(buildRepeatedRegionEvidence(input).pool).toEqual({
      loadedObservationCount: 3,
      eligibleObservationCount: 3,
      abstainedIdentityIds: [],
    });
    expect(buildRepeatedRegionEvidence([])).toEqual({
      regions: [],
      byGroupKey: new Map(),
      pool: { loadedObservationCount: 0, eligibleObservationCount: 0, abstainedIdentityIds: [] },
    });
  });
});

import { describe, expect, it } from 'vitest';

import type { PendingMergeSuggestion } from '../../../../api/recognition/types';
import {
  authoritativeMergeSurvivor,
  resolveMergeSurvivor,
  resolveMergeSurvivorFromResponse,
} from '../resolveMergeSurvivor';

const base = (overrides: Partial<PendingMergeSuggestion> = {}): PendingMergeSuggestion => ({
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.9,
  status: 'pending',
  cluster_a_label: null,
  cluster_b_label: null,
  cluster_a_identity_count: 1,
  cluster_b_identity_count: 1,
  ...overrides,
});

describe('resolveMergeSurvivor', () => {
  it('prefers the side with a meaningful (human) label', () => {
    const result = resolveMergeSurvivor(
      base({
        cluster_a_label: 'cluster-auto',
        cluster_b_label: 'Alice',
        cluster_a_identity_count: 10,
        cluster_b_identity_count: 1,
      }),
    );
    expect(result).toEqual({ survivorId: 'cluster-b', retiredId: 'cluster-a' });
  });

  it('prefers higher identity_count when labels are equally meaningful', () => {
    const result = resolveMergeSurvivor(
      base({
        cluster_a_label: 'Alice',
        cluster_b_label: 'Bob',
        cluster_a_identity_count: 2,
        cluster_b_identity_count: 5,
      }),
    );
    expect(result).toEqual({ survivorId: 'cluster-b', retiredId: 'cluster-a' });
  });

  it('breaks remaining ties with lexicographic id (higher wins, A preferred on full tie)', () => {
    const byId = resolveMergeSurvivor(
      base({
        cluster_a_id: 'aaa',
        cluster_b_id: 'zzz',
        cluster_a_label: null,
        cluster_b_label: null,
        cluster_a_identity_count: 1,
        cluster_b_identity_count: 1,
      }),
    );
    expect(byId).toEqual({ survivorId: 'zzz', retiredId: 'aaa' });

    // Equal rank fields including id impossible for distinct clusters; equal counts + both null labels
    // with a_id > b_id prefers A when ranks equal only if ids equal — with a > b, A wins via id.
    const aWinsById = resolveMergeSurvivor(
      base({
        cluster_a_id: 'zzz',
        cluster_b_id: 'aaa',
        cluster_a_label: null,
        cluster_b_label: null,
        cluster_a_identity_count: 1,
        cluster_b_identity_count: 1,
      }),
    );
    expect(aWinsById).toEqual({ survivorId: 'zzz', retiredId: 'aaa' });
  });

  it('BR-69: matches the backend (no trim) — a whitespace-padded label is meaningful', () => {
    // Backend `_is_meaningful_label` does not trim: '  cluster-auto' does NOT
    // start with 'cluster-' (leading spaces), so it ranks as meaningful. The old
    // trimming client replica disagreed and mis-picked the survivor.
    const result = resolveMergeSurvivor(
      base({
        cluster_a_id: 'aaa',
        cluster_b_id: 'bbb',
        cluster_a_label: '  cluster-auto',
        cluster_b_label: null,
        cluster_a_identity_count: 1,
        cluster_b_identity_count: 1,
      }),
    );
    expect(result).toEqual({ survivorId: 'aaa', retiredId: 'bbb' });
  });

  it('treats null identity counts as 0', () => {
    const result = resolveMergeSurvivor(
      base({
        cluster_a_label: null,
        cluster_b_label: null,
        cluster_a_identity_count: null,
        cluster_b_identity_count: 1,
      }),
    );
    expect(result).toEqual({ survivorId: 'cluster-b', retiredId: 'cluster-a' });
  });
});

describe('resolveMergeSurvivorFromResponse (authoritative ids)', () => {
  it('uses source/target response ids over client rank', () => {
    // Client rank would pick larger A; authoritative ids flip to B as survivor.
    const result = resolveMergeSurvivorFromResponse(
      base({
        cluster_a_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        cluster_b_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        cluster_a_label: null,
        cluster_b_label: 'Named Person',
        cluster_a_identity_count: 50,
        cluster_b_identity_count: 2,
        source_cluster_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        target_cluster_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      }),
    );
    expect(result).toEqual({
      survivorId: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      retiredId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    });
  });

  it('user_confirmed-flip fixture: response ids beat client identity_count rank', () => {
    // Mirrors backend test_select_merge_target_user_confirmed_flips_survivor_over_larger_count:
    // smaller user_confirmed cluster is survivor even when the other side has
    // far more members. Client rank cannot see user_confirmed and would pick the
    // larger side — red against old client-rank-only accept path.
    const largerUnconfirmed = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
    const smallerConfirmed = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    const response = base({
      cluster_a_id: largerUnconfirmed,
      cluster_b_id: smallerConfirmed,
      cluster_a_label: null,
      cluster_b_label: 'Named Person',
      cluster_a_identity_count: 50,
      cluster_b_identity_count: 2,
      // Authoritative: user_confirmed on B → B survives, A retired.
      source_cluster_id: largerUnconfirmed,
      target_cluster_id: smallerConfirmed,
    });

    // Client rank alone: A has higher identity_count (50 > 2) and B has the only
    // meaningful label — label wins for B. Force a pure count flip by giving both
    // meaningful labels so count would pick A while response picks B.
    const countFlip = base({
      cluster_a_id: largerUnconfirmed,
      cluster_b_id: smallerConfirmed,
      cluster_a_label: 'Alice',
      cluster_b_label: 'Bob',
      cluster_a_identity_count: 50,
      cluster_b_identity_count: 2,
      source_cluster_id: largerUnconfirmed,
      target_cluster_id: smallerConfirmed,
    });

    // Without authoritative ids, client rank picks larger A.
    expect(resolveMergeSurvivor(countFlip)).toEqual({
      survivorId: largerUnconfirmed,
      retiredId: smallerConfirmed,
    });
    // With response ids, accept path records the user_confirmed survivor.
    expect(resolveMergeSurvivorFromResponse(countFlip)).toEqual({
      survivorId: smallerConfirmed,
      retiredId: largerUnconfirmed,
    });
    expect(authoritativeMergeSurvivor(response)).toEqual({
      survivorId: smallerConfirmed,
      retiredId: largerUnconfirmed,
    });
  });

  it('falls back to client rank when response omits source/target (older backend)', () => {
    const result = resolveMergeSurvivorFromResponse(
      base({
        cluster_a_label: null,
        cluster_b_label: 'Alice',
        cluster_a_identity_count: 10,
        cluster_b_identity_count: 1,
        source_cluster_id: null,
        target_cluster_id: null,
      }),
    );
    expect(result).toEqual({ survivorId: 'cluster-b', retiredId: 'cluster-a' });
    expect(authoritativeMergeSurvivor(base({ source_cluster_id: null, target_cluster_id: null }))).toBeNull();
  });

  it('ignores identical source/target and falls back', () => {
    const result = resolveMergeSurvivorFromResponse(
      base({
        cluster_a_label: null,
        cluster_b_label: 'Alice',
        source_cluster_id: 'same',
        target_cluster_id: 'same',
      }),
    );
    expect(result).toEqual({ survivorId: 'cluster-b', retiredId: 'cluster-a' });
  });
});

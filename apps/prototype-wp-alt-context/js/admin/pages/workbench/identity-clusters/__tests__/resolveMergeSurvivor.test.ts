import { describe, expect, it } from 'vitest';

import type { PendingMergeSuggestion } from '../../../../api/recognition/types';
import {
  authoritativeMergeSurvivor,
  isMeaningfulMergeLabel,
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

describe('isMeaningfulMergeLabel (HARM-F5 / DATA-14)', () => {
  it.each([
    ['Cluster-9f2', false],
    [' cluster-9f2', false],
    ['cluster_9f2', false],
    ['Ada Lovelace', true],
  ])('%j is meaningful → %s', (label, expected) => {
    expect(isMeaningfulMergeLabel(label)).toBe(expected);
  });
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

  it('HARM-F5: whitespace-padded reserved labels are not meaningful', () => {
    // Backend `is_reserved_label_shape` trims + lowercases; padded `cluster-*`
    // must not win the client-rank fallback.
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
    expect(isMeaningfulMergeLabel('  cluster-auto')).toBe(false);
    expect(result).toEqual({ survivorId: 'bbb', retiredId: 'aaa' });
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

  it('user_confirmed-flip fixture: response ids CONTRADICT client rank (sole discriminator story)', () => {
    // E215-BR-03: mirrors backend ranking where user_confirmed is the SOLE
    // discriminator — labels equal-rank and counts favor the loser. Client rank
    // cannot see user_confirmed and would pick larger A; response stamps B.
    const largerUnconfirmed = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
    const smallerConfirmed = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    const countFlip = base({
      cluster_a_id: largerUnconfirmed,
      cluster_b_id: smallerConfirmed,
      cluster_a_label: 'Alice',
      cluster_b_label: 'Bob',
      cluster_a_identity_count: 50,
      cluster_b_identity_count: 2,
      // Authoritative: user_confirmed on B → B survives, A retired.
      source_cluster_id: largerUnconfirmed,
      target_cluster_id: smallerConfirmed,
    });

    // Without authoritative ids, client rank picks larger A (count favors loser).
    expect(resolveMergeSurvivor(countFlip)).toEqual({
      survivorId: largerUnconfirmed,
      retiredId: smallerConfirmed,
    });
    // With response ids, accept path records the user_confirmed survivor — CONTRADICTS rank.
    expect(resolveMergeSurvivorFromResponse(countFlip)).toEqual({
      survivorId: smallerConfirmed,
      retiredId: largerUnconfirmed,
    });
    expect(authoritativeMergeSurvivor(countFlip)).toEqual({
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

  it('E215-BR-04: mismatched source/target not in {a,b} fall back to client rank', () => {
    const result = resolveMergeSurvivorFromResponse(
      base({
        cluster_a_id: 'cluster-a',
        cluster_b_id: 'cluster-b',
        cluster_a_label: null,
        cluster_b_label: 'Alice',
        cluster_a_identity_count: 10,
        cluster_b_identity_count: 1,
        // Foreign ids must not be trusted.
        source_cluster_id: 'cluster-foreign-1',
        target_cluster_id: 'cluster-foreign-2',
      }),
    );
    expect(authoritativeMergeSurvivor(
      base({
        source_cluster_id: 'cluster-foreign-1',
        target_cluster_id: 'cluster-foreign-2',
      }),
    )).toBeNull();
    // Client rank: B has the meaningful label.
    expect(result).toEqual({ survivorId: 'cluster-b', retiredId: 'cluster-a' });
  });
});

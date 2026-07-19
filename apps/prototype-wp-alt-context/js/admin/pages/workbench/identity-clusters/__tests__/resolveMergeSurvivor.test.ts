import { describe, expect, it } from 'vitest';

import type { PendingMergeSuggestion } from '../../../../api/recognition/types';
import { resolveMergeSurvivor } from '../resolveMergeSurvivor';

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

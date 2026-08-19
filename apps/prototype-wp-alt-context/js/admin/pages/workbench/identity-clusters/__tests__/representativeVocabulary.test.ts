import { describe, expect, it } from 'vitest';

import { gatedClusterCopy, repairGatedCount } from '../representativeVocabulary';

describe('repairGatedCount', () => {
  it('R3-03: zero evidence and zero unlabeled does not invent a group', () => {
    expect(repairGatedCount(0, 0)).toBe(0);
    expect(gatedClusterCopy(0)).toBe('Some groups are missing face data');
  });

  it('R5-02: an empty served page uses server-scoped wording', () => {
    expect(gatedClusterCopy(24, true, 0)).not.toMatch(/on this page/);
    expect(gatedClusterCopy(24, true, 0)).toMatch(/elsewhere/);
  });

  it('R5-02: a non-empty page keeps page-scoped wording', () => {
    expect(gatedClusterCopy(3, true, 9)).toMatch(/on this page/);
  });
});

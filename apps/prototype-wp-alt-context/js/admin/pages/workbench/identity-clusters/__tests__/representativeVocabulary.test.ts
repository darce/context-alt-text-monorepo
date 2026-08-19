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

  it('R7-03: the three gatedClusterCopy branches are exact sentences', () => {
    expect(gatedClusterCopy(3, true, 0)).toBe('3 groups elsewhere are missing face data');
    expect(gatedClusterCopy(3, true, 2)).toBe('At least 3 groups on this page missing face data');
    expect(gatedClusterCopy(3, false, 2)).toBe('3 groups missing face data');
  });
});

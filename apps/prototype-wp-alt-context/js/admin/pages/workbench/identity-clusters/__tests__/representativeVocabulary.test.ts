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

  // R8-01 / TEST-15: servedCount=N and servedCount=0 must be different sentences.
  // A fixture that passes under both branches cannot kill the servedCount=0 mutant.
  it('R8-01: on-page gated clusters are not described as elsewhere', () => {
    expect(gatedClusterCopy(3, false, 3)).toBe('3 groups missing face data');
    expect(gatedClusterCopy(3, false, 0)).toBe('3 groups elsewhere are missing face data');
    expect(gatedClusterCopy(3, false, 3)).not.toBe(gatedClusterCopy(3, false, 0));
  });

  it('R8-01: repairGatedCount prefers page-local zeros over server-wide unlabeled', () => {
    expect(repairGatedCount(3, 7)).toBe(3);
    expect(repairGatedCount(0, 7)).toBe(7);
    expect(repairGatedCount(3, 7)).not.toBe(7);
  });
});

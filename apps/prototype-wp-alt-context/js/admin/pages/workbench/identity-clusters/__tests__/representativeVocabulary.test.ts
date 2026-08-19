import { describe, expect, it } from 'vitest';

import { gatedClusterCopy, repairGatedCount } from '../representativeVocabulary';

describe('repairGatedCount', () => {
  it('R3-03: zero evidence and zero unlabeled does not invent a group', () => {
    expect(repairGatedCount(0, 0)).toBe(0);
    expect(gatedClusterCopy(0)).toBe('Some groups are missing face data');
  });
});

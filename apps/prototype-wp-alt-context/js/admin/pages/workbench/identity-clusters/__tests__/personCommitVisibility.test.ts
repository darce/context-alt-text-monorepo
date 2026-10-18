import { describe, expect, it } from 'vitest';

import { NEXT_ACTION_KIND } from '../reviewQueueDriver';
import {
  hasPersonCommitClusterId,
  isPersonCommitPrimaryKind,
  shouldShowPersonCommit,
} from '../personCommitVisibility';

describe('personCommitVisibility — per-kind matrix', () => {
  it('shows person-commit for NAME and CLUSTER when clusterId is present', () => {
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.NAME, 'cluster-1')).toBe(true);
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.CLUSTER, 'cluster-2')).toBe(true);
    expect(isPersonCommitPrimaryKind(NEXT_ACTION_KIND.NAME)).toBe(true);
    expect(isPersonCommitPrimaryKind(NEXT_ACTION_KIND.CLUSTER)).toBe(true);
  });

  it('shows person-commit for ASSIGNMENT only when clusterId is non-null', () => {
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.ASSIGNMENT, 'cluster-1')).toBe(true);
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.ASSIGNMENT, null)).toBe(false);
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.ASSIGNMENT, '')).toBe(false);
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.ASSIGNMENT, undefined)).toBe(false);
    expect(isPersonCommitPrimaryKind(NEXT_ACTION_KIND.ASSIGNMENT)).toBe(false);
  });

  it('never shows person-commit for MERGE', () => {
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.MERGE, 'cluster-1')).toBe(false);
    expect(shouldShowPersonCommit(NEXT_ACTION_KIND.MERGE, null)).toBe(false);
    expect(isPersonCommitPrimaryKind(NEXT_ACTION_KIND.MERGE)).toBe(false);
  });

  it('hasPersonCommitClusterId rejects empty/whitespace', () => {
    expect(hasPersonCommitClusterId('  ')).toBe(false);
    expect(hasPersonCommitClusterId('id')).toBe(true);
  });
});

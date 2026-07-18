import { describe, expect, it } from 'vitest';

import {
  DEFAULT_QUEUE_STATE,
  filterToKindParam,
  kindParamToFilter,
  parseQueueState,
  serializeQueueState,
} from '../workbenchQueueUrl';
import { REVIEW_QUEUE_FILTER } from '../../pages/workbench/identity-clusters/reviewQueueDriver';

describe('workbenchQueueUrl', () => {
  it('parses valid rq triples', () => {
    expect(parseQueueState('assignment.strong.4')).toEqual({
      kind: 'assignment',
      band: 'strong',
      index: 4,
    });
    expect(parseQueueState('merge.weaker.0')).toEqual({
      kind: 'merge',
      band: 'weaker',
      index: 0,
    });
  });

  it('returns defaults for omitted or malformed values (never throws)', () => {
    expect(parseQueueState(null)).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState(undefined)).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('')).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('assignment.all')).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('nope.all.1')).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('all.nope.1')).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('all.all.-1')).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('all.all.01')).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('all.all.1.5')).toEqual(DEFAULT_QUEUE_STATE);
    expect(parseQueueState('all.all.abc')).toEqual(DEFAULT_QUEUE_STATE);
  });

  it('omits default serialization and round-trips non-defaults', () => {
    expect(serializeQueueState(DEFAULT_QUEUE_STATE)).toBeNull();
    expect(serializeQueueState({ kind: 'assignment', band: 'all', index: 0 })).toBe('assignment.all.0');
    expect(serializeQueueState({ kind: 'all', band: 'all', index: 2 })).toBe('all.all.2');
    expect(serializeQueueState({ kind: 'assignment', band: 'strong', index: 1 })).toBe(
      'assignment.strong.1',
    );
    expect(parseQueueState(serializeQueueState({ kind: 'merge', band: 'weaker', index: 9 }))).toEqual({
      kind: 'merge',
      band: 'weaker',
      index: 9,
    });
  });

  it('maps kind param ↔ driver filter (sr-007)', () => {
    expect(kindParamToFilter('assignment')).toBe(REVIEW_QUEUE_FILTER.ASSIGNMENT);
    expect(kindParamToFilter('merge')).toBe(REVIEW_QUEUE_FILTER.MERGE);
    expect(kindParamToFilter('all')).toBe(REVIEW_QUEUE_FILTER.ALL);
    expect(filterToKindParam(REVIEW_QUEUE_FILTER.ASSIGNMENT)).toBe('assignment');
    expect(filterToKindParam(REVIEW_QUEUE_FILTER.MERGE)).toBe('merge');
    expect(filterToKindParam(REVIEW_QUEUE_FILTER.ALL)).toBe('all');
  });
});

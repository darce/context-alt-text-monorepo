/**
 * E21-5 Slice 5 — multi-select bulk state machine + matrix M1.
 *
 * Named exits: bulk-undo=0 POSTs; single→bulk + bulk→single flush ordering;
 * bulk×unmount (item-1 + remainder cancelled); in-hold id exclusion;
 * PR-38 labels; PA-27 partial failure; zero legacy bulk-accept; M1 exact ids.
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  bulkCommitLabel,
  bulkHoldStatusCopy,
  sharedSelectionLabel,
  useBulkReviewCommit,
  type BulkCommitItem,
  type BulkCommitOneFn,
} from '../useBulkReviewCommit';
import { UNDO_HOLD_MS, type ScheduleCommitResult } from '../useSuggestionReviewMutations';

const expireBulkHold = async (): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS);
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('bulkCommitLabel / sharedSelectionLabel (PR-38)', () => {
  it('renders Accept N for <label> only when every selected item shares one label', () => {
    expect(sharedSelectionLabel(['Maria', 'Maria', 'Maria'])).toBe('Maria');
    expect(bulkCommitLabel(3, 'Maria')).toBe('Accept 3 for Maria');
  });

  it('renders Accept N selected when labels are heterogeneous or empty', () => {
    expect(sharedSelectionLabel(['Maria', 'Alex'])).toBeNull();
    expect(sharedSelectionLabel([null, 'Maria'])).toBeNull();
    expect(bulkCommitLabel(2, null)).toBe('Accept 2 selected');
  });

  it('exports Saving N hold copy', () => {
    expect(bulkHoldStatusCopy(4)).toBe('Saving 4… — Undo');
  });
});

describe('useBulkReviewCommit (PR-30 state machine)', () => {
  let selectedIds: Set<string>;
  let onSelectedIdsChange: (next: Set<string>) => void;
  let commitOne: BulkCommitOneFn;
  let flushHeldSingle: () => Promise<ScheduleCommitResult | null>;
  let setBulkActionActive: (active: boolean) => void;
  let isBulkActiveRef: { current: boolean };
  let awaitBulkIdleOrFlushRef: { current: (() => Promise<void>) | null };
  let commitCalls: string[];

  const items: Record<string, BulkCommitItem> = {
    a: { suggestionId: 'a', commitKind: 'accept', label: 'Maria' },
    b: { suggestionId: 'b', commitKind: 'accept', label: 'Maria' },
    c: { suggestionId: 'c', commitKind: 'accept', label: 'Maria' },
  };

  const resolveItems = (ids: readonly string[]): BulkCommitItem[] =>
    ids.map((id) => items[id]).filter(Boolean);

  const renderBulk = (heldSingleSuggestionId: string | null = null) =>
    renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange,
        resolveItems,
        flushHeldSingle,
        commitOne,
        heldSingleSuggestionId,
        setBulkActionActive,
        isBulkActiveRef,
        awaitBulkIdleOrFlushRef,
      }),
    );

  beforeEach(() => {
    vi.useFakeTimers();
    selectedIds = new Set(['a', 'b', 'c']);
    commitCalls = [];
    onSelectedIdsChange = (next: Set<string>) => {
      selectedIds = next;
    };
    commitOne = (_kind, id) => {
      commitCalls.push(id);
      return Promise.resolve('committed' as const);
    };
    flushHeldSingle = () => Promise.resolve(null);
    setBulkActionActive = () => undefined;
    isBulkActiveRef = { current: false };
    awaitBulkIdleOrFlushRef = { current: null };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('matrix M1 multi-select-bulk: exact mutated id set; zero legacy bulk-accept', async () => {
    const { result } = renderBulk();

    await act(async () => {
      await result.current.initiateBulk();
    });
    expect(result.current.bulk.phase).toBe('holding');
    expect(result.current.bulkHoldAnnounce).toBe('Saving 3… — Undo');
    expect(commitCalls).toEqual([]);

    await expireBulkHold();

    expect(commitCalls).toEqual(['a', 'b', 'c']);
  });

  it('bulk-undo cancels entire set — 0 POSTs; selection unchanged', async () => {
    const { result } = renderBulk();

    await act(async () => {
      await result.current.initiateBulk();
    });
    act(() => {
      result.current.undoBulk();
    });

    await expireBulkHold();
    expect(commitCalls).toEqual([]);
    expect(result.current.bulk.phase).toBe('idle');
    expect(selectedIds.size).toBe(3);
  });

  it('single→bulk flush ordering: initiate flushes held single first', async () => {
    const flushOrder: string[] = [];
    flushHeldSingle = () => {
      flushOrder.push('single-flush');
      return Promise.resolve({
        outcome: 'committed',
        kind: 'accept',
        suggestionId: 'x',
      });
    };
    commitOne = (_kind, id) => {
      flushOrder.push(`commit:${id}`);
      return Promise.resolve('committed' as const);
    };

    const { result } = renderBulk();
    await act(async () => {
      await result.current.initiateBulk();
    });
    expect(flushOrder).toEqual(['single-flush']);
    expect(result.current.bulk.phase).toBe('holding');

    await expireBulkHold();
    expect(flushOrder).toEqual(['single-flush', 'commit:a', 'commit:b', 'commit:c']);
  });

  it('bulk→single flush ordering: awaitBulkIdleOrFlush fires sequence before returning', async () => {
    const { result } = renderBulk();
    await act(async () => {
      await result.current.initiateBulk();
    });
    expect(result.current.bulk.phase).toBe('holding');

    await act(async () => {
      await result.current.awaitBulkIdleOrFlush();
    });

    expect(commitCalls).toEqual(['a', 'b', 'c']);
    expect(result.current.bulk.phase).toBe('idle');
  });

  it('bulk×unmount: fires item 1 only; remainder stays selected', async () => {
    const { result, unmount } = renderBulk();
    await act(async () => {
      await result.current.initiateBulk();
    });
    expect(result.current.bulk.phase).toBe('holding');

    unmount();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(commitCalls).toEqual(['a']);
    expect(selectedIds.has('b')).toBe(true);
    expect(selectedIds.has('c')).toBe(true);
  });

  it('in-hold single id cannot be selected (PR-30 exclusion)', () => {
    selectedIds = new Set();
    const { result } = renderBulk('held-id');
    expect(result.current.isIdSelectable('held-id')).toBe(false);
    expect(result.current.isIdSelectable('other')).toBe(true);
  });

  it('PA-27 partial failure: stop-on-first-failure; remainder stays selected; alert counts', async () => {
    commitOne = (_kind, id) => {
      commitCalls.push(id);
      if (id === 'b') {
        return Promise.resolve('failed' as const);
      }
      return Promise.resolve('committed' as const);
    };

    let liveSelection = new Set(['a', 'b', 'c']);
    onSelectedIdsChange = (next: Set<string>) => {
      liveSelection = next;
    };

    const { result, rerender } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds: liveSelection,
        onSelectedIdsChange,
        resolveItems,
        flushHeldSingle,
        commitOne,
        heldSingleSuggestionId: null,
        setBulkActionActive,
        isBulkActiveRef,
        awaitBulkIdleOrFlushRef,
      }),
    );

    await act(async () => {
      await result.current.initiateBulk();
    });
    await expireBulkHold();
    rerender();

    expect(commitCalls).toEqual(['a', 'b']);
    expect(result.current.bulk.phase).toBe('partial_failed');
    expect(result.current.bulk.partialFailure).toMatchObject({
      landed: 1,
      failed: 1,
      notAttempted: 1,
      failedLabel: 'Maria',
    });
    expect(result.current.bulk.partialFailure?.message).toContain('1 of 3 accepted');
    expect(result.current.bulk.partialFailure?.message).toContain('not attempted');
    expect(liveSelection.has('a')).toBe(false);
    expect(liveSelection.has('b')).toBe(true);
    expect(liveSelection.has('c')).toBe(true);
  });

  it('does not call commitOne when selection empty', async () => {
    selectedIds = new Set();
    const { result } = renderBulk();
    await act(async () => {
      await result.current.initiateBulk();
    });
    expect(result.current.bulk.phase).toBe('idle');
    expect(commitCalls).toEqual([]);
  });
});

describe('matrix M1 single / review-each helpers', () => {
  it('documents single-path exact id via commitOne mock contract', async () => {
    const mutated: string[] = [];
    const commitOne: BulkCommitOneFn = (_kind, id) => {
      mutated.push(id);
      return Promise.resolve('committed' as const);
    };
    let selectedIds = new Set(['only-1']);
    const isBulkActiveRef = { current: false };
    const awaitBulkIdleOrFlushRef: { current: (() => Promise<void>) | null } = {
      current: null,
    };

    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange: (next) => {
          selectedIds = next;
        },
        resolveItems: (ids) =>
          ids.map((id) => ({ suggestionId: id, commitKind: 'accept' as const, label: 'X' })),
        flushHeldSingle: () => Promise.resolve(null),
        commitOne,
        heldSingleSuggestionId: null,
        setBulkActionActive: () => undefined,
        isBulkActiveRef,
        awaitBulkIdleOrFlushRef,
      }),
    );

    await act(async () => {
      await result.current.initiateBulk();
    });
    await expireBulkHold();
    expect(mutated).toEqual(['only-1']);
    vi.useRealTimers();
  });
});

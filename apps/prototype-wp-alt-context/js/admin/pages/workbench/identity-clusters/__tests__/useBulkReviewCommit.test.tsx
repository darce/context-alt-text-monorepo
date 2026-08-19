/**
 * E21-5 Slice 5 — multi-select bulk state machine + matrix M1 + BR-46..56.
 *
 * Named exits: bulk-undo=0 POSTs; single→bulk + bulk→single flush ordering;
 * bulk×unmount (item-1 + remainder cancelled); mid-sequence unmount (BR-46);
 * in-hold id exclusion; PR-38 labels; PA-27 partial failure; BR-50 prune-at-fire;
 * zero legacy bulk-accept; M1 exact ids (single / review-each / bulk).
 */

import type { ReactNode } from 'react';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../../../api/recognition';
import * as rosterApi from '../../../../api/rosterApi';
import {
  buildPartialFailureMessage,
  bulkCommitLabel,
  bulkCommittingStatusCopy,
  bulkHoldStatusCopy,
  sharedSelectionLabel,
  useBulkReviewCommit,
  type BulkCommitItem,
  type BulkCommitOneFn,
} from '../useBulkReviewCommit';
import {
  HOLD_STATUS_COPY,
  UNDO_HOLD_MS,
  useSuggestionReviewMutations,
  type ScheduleCommitResult,
} from '../useSuggestionReviewMutations';

vi.mock('../../../../api/recognition', () => ({
  acceptSuggestion: vi.fn(),
  rejectSuggestion: vi.fn(),
  acceptMergeSuggestion: vi.fn(),
  rejectMergeSuggestion: vi.fn(),
  acceptNameSuggestion: vi.fn(),
  rejectNameSuggestion: vi.fn(),
  bulkAcceptSuggestions: vi.fn(),
}));

vi.mock('../../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn(),
  listRosterEntries: vi.fn().mockResolvedValue([]),
}));

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

  it('exports Saving N hold copy and committing copy without Undo (BR-55)', () => {
    expect(bulkHoldStatusCopy(4)).toBe('Saving 4… — Undo');
    expect(bulkCommittingStatusCopy(4)).toBe('Saving 4…');
    expect(bulkCommittingStatusCopy(4)).not.toContain('Undo');
  });

  it('BR-53: PA-27 pinned partial-failure copy structure', () => {
    expect(buildPartialFailureMessage(1, 3, 'Maria', 1)).toBe(
      "1 of 3 accepted — 'Accept' failed for Maria; 1 not attempted",
    );
    expect(buildPartialFailureMessage(0, 2, null, 1)).toBe(
      "0 of 2 accepted — 'Accept' failed for item; 1 not attempted",
    );
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

  it('BR-47(a): flushed single id dropped from bulk items — exactly 1 POST for shared id', async () => {
    // Single hold is on 'a' which is also selected. After flush, bulk must not re-POST a.
    flushHeldSingle = () =>
      Promise.resolve({
        outcome: 'committed',
        kind: 'accept',
        suggestionId: 'a',
      });
    // Simulate host dropFromSelection after flush by also dropping in onSelectedIdsChange
    // path that initiateBulk already does via dropFromSelection.
    const { result } = renderBulk();
    await act(async () => {
      await result.current.initiateBulk();
    });
    // 'a' dropped from selection after flush
    expect(selectedIds.has('a')).toBe(false);
    expect(result.current.bulk.heldIds).toEqual(['b', 'c']);

    await expireBulkHold();
    expect(commitCalls).toEqual(['b', 'c']);
    expect(commitCalls).not.toContain('a');
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

  it('S3-02/GROK-03: awaitBulkIdleOrFlush serializes behind an in-flight bulk initiation (no TOCTOU no-op)', async () => {
    // Gate the single-flush so initiateBulk parks in its flush window: phase still 'idle',
    // hold not yet open, but a bulk initiation IS in flight.
    let releaseFlush!: () => void;
    const flushGate = new Promise<void>((r) => {
      releaseFlush = r;
    });
    flushHeldSingle = () => flushGate.then(() => null);

    const { result } = renderBulk();

    // Fire initiate but do NOT await — it parks on flushGate.
    let initiateDone = false;
    act(() => {
      void result.current.initiateBulk().then(() => {
        initiateDone = true;
      });
    });
    expect(result.current.bulk.phase).toBe('idle');
    expect(commitCalls).toEqual([]);

    // A concurrent single/person commit awaits the bulk. With the TOCTOU bug this resolves
    // immediately (no-op) because phase is still 'idle' — letting the single interleave.
    let awaitResolved = false;
    let awaitP!: Promise<void>;
    act(() => {
      awaitP = result.current.awaitBulkIdleOrFlush();
      void awaitP.then(() => {
        awaitResolved = true;
      });
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // FIXED: awaitBulk must still be pending — serialized behind the initiation.
    expect(awaitResolved).toBe(false);
    expect(commitCalls).toEqual([]);

    // Release the flush → initiation opens the hold → awaitBulk (having waited) fires the
    // sequence before it resolves, preserving bulk→single ordering.
    await act(async () => {
      releaseFlush();
      await awaitP;
    });

    expect(initiateDone).toBe(true);
    expect(commitCalls).toEqual(['a', 'b', 'c']);
    expect(awaitResolved).toBe(true);
    expect(result.current.bulk.phase).toBe('idle');
  });

  it('GROK-03 hardening: a rejecting initiation flush does not reject awaitBulkIdleOrFlush', async () => {
    // flushHeldSingle should never throw in production, but if it does, awaitBulk must
    // resolve to a deterministic idle no-op — never reject into the caller's commit path.
    let rejectFlush!: (e: unknown) => void;
    const flushGate = new Promise<void>((_, rej) => {
      rejectFlush = rej;
    });
    flushHeldSingle = () => flushGate.then(() => null);

    const { result } = renderBulk();

    act(() => {
      void result.current.initiateBulk().catch(() => undefined);
    });

    // Capture awaitBulk while the initiation promise is still in flight.
    let awaitErr: unknown = null;
    let awaitP!: Promise<void>;
    act(() => {
      awaitP = result.current.awaitBulkIdleOrFlush();
      void awaitP.catch((e) => {
        awaitErr = e;
      });
    });

    await act(async () => {
      rejectFlush(new Error('flush boom'));
      await awaitP.catch(() => undefined);
    });

    expect(awaitErr).toBeNull();
    expect(commitCalls).toEqual([]);
    expect(result.current.bulk.phase).toBe('idle');
  });

  it('bulk×unmount while holding: fires item 1 only; remainder stays selected', async () => {
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

  it('TEST-15: unmount while holding after deselecting items[0] — commits next survivor, not deselected id', async () => {
    // Discrimination guard: old unmount used raw held.items[0]; BR-50/BR-62 re-filter
    // at unmount must skip the deselected first id and fire the next live survivor.
    let liveSelection = new Set(['a', 'b', 'c']);
    onSelectedIdsChange = (next: Set<string>) => {
      liveSelection = next;
      selectedIds = next;
    };

    const { result, unmount, rerender } = renderHook(() =>
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
    expect(result.current.bulk.phase).toBe('holding');
    expect(result.current.bulk.heldIds[0]).toBe('a');

    // Deselect the first held id during the hold (live selection leaves the set).
    act(() => {
      const next = new Set(liveSelection);
      next.delete('a');
      onSelectedIdsChange(next);
    });
    rerender();
    expect(liveSelection.has('a')).toBe(false);

    unmount();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(commitCalls).not.toContain('a');
    expect(commitCalls).toEqual(['b']);
  });

  it('BR-46: unmount mid-sequence after item1 — in-flight item2 finishes; remainder selected', async () => {
    let resolveB: ((v: 'committed' | 'failed') => void) | null = null;
    const bGate = new Promise<'committed' | 'failed'>((resolve) => {
      resolveB = resolve;
    });

    commitOne = (_kind, id) => {
      commitCalls.push(id);
      if (id === 'a') {
        return Promise.resolve('committed' as const);
      }
      if (id === 'b') {
        return bGate;
      }
      return Promise.resolve('committed' as const);
    };

    let liveSelection = new Set(['a', 'b', 'c']);
    onSelectedIdsChange = (next: Set<string>) => {
      liveSelection = next;
      selectedIds = next;
    };

    const { result, unmount } = renderHook(() =>
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
    expect(result.current.bulk.phase).toBe('holding');

    // Kick the sequence; stop while b's POST is in flight.
    let seqDone!: Promise<void>;
    await act(async () => {
      seqDone = result.current.awaitBulkIdleOrFlush();
      // Flush microtasks so a resolves and b starts, but do not await b.
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(commitCalls).toEqual(['a', 'b']);
    expect(result.current.bulk.phase).toBe('committing');

    unmount();

    await act(async () => {
      resolveB?.('committed');
      await seqDone;
    });

    // Exactly 2 POSTs — c cancelled; c remains selected
    expect(commitCalls).toEqual(['a', 'b']);
    expect(liveSelection.has('c')).toBe(true);
    expect(liveSelection.has('a')).toBe(false);
  });

  it('in-hold single id cannot be selected (PR-30 exclusion)', () => {
    selectedIds = new Set();
    const { result } = renderBulk('held-id');
    expect(result.current.isIdSelectable('held-id')).toBe(false);
    expect(result.current.isIdSelectable('other')).toBe(true);
  });

  it('BR-47: isIdInBulkSelection is true for selected ids', () => {
    const { result } = renderBulk();
    expect(result.current.isIdInBulkSelection('a')).toBe(true);
    expect(result.current.isIdInBulkSelection('z')).toBe(false);
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
    expect(result.current.bulk.partialFailure?.message).toBe(
      "1 of 3 accepted — 'Accept' failed for Maria; 1 not attempted",
    );
    expect(liveSelection.has('a')).toBe(false);
    expect(liveSelection.has('b')).toBe(true);
    expect(liveSelection.has('c')).toBe(true);
  });

  it('BR-50: prune during hold — pruned id not POSTed; hold count at fire uses filtered set', async () => {
    let liveSelection = new Set(['a', 'b', 'c']);
    onSelectedIdsChange = (next: Set<string>) => {
      liveSelection = next;
      selectedIds = next;
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
    expect(result.current.bulk.phase).toBe('holding');
    expect(result.current.bulk.holdCount).toBe(3);

    // Prune b during hold (left the projection)
    act(() => {
      const dropped = result.current.pruneMissingIds(new Set(['a', 'c']));
      expect(dropped).toBe(1);
    });
    rerender();
    expect(liveSelection.has('b')).toBe(false);

    await expireBulkHold();
    expect(commitCalls).toEqual(['a', 'c']);
    expect(commitCalls).not.toContain('b');
  });

  it('BR-62: filter change during hold narrows fired set to live selection ∩ filters', async () => {
    // resolveItems honors the active KIND∩band view (host wiring); simulate a
    // URL-driven band change during the hold by shrinking the allowed set.
    let allowedByFilters = new Set(['a', 'b', 'c']);
    const filterAwareResolveItems = (ids: readonly string[]): BulkCommitItem[] =>
      ids
        .filter((id) => allowedByFilters.has(id))
        .map((id) => items[id])
        .filter(Boolean);

    const { result } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange,
        resolveItems: filterAwareResolveItems,
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
    expect(result.current.bulk.phase).toBe('holding');
    expect(result.current.bulk.holdCount).toBe(3);

    // Band change via URL during the hold: only 'a' stays in the live view.
    allowedByFilters = new Set(['a']);

    await expireBulkHold();
    // Chosen honest behavior: the fired set respects the new intersection.
    expect(commitCalls).toEqual(['a']);
    expect(commitCalls).not.toContain('b');
    expect(commitCalls).not.toContain('c');
    // Unfired ids stay selected — nothing committed outside the live view.
    expect(selectedIds.has('b')).toBe(true);
    expect(selectedIds.has('c')).toBe(true);
  });

  it('BR-55: committing-phase announce drops Undo suffix', async () => {
    let resolveA: ((v: 'committed' | 'failed') => void) | null = null;
    commitOne = (_kind, id) => {
      commitCalls.push(id);
      if (id === 'a') {
        return new Promise((resolve) => {
          resolveA = resolve;
        });
      }
      return Promise.resolve('committed' as const);
    };

    const { result } = renderBulk();
    await act(async () => {
      await result.current.initiateBulk();
    });
    expect(result.current.bulkHoldAnnounce).toBe('Saving 3… — Undo');

    let seqDone!: Promise<void>;
    await act(async () => {
      seqDone = result.current.awaitBulkIdleOrFlush();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.bulk.phase).toBe('committing');
    expect(result.current.bulkHoldAnnounce).toBe('Saving 3…');
    expect(result.current.bulkHoldAnnounce).not.toContain('Undo');

    await act(async () => {
      resolveA?.('committed');
      await seqDone;
    });
  });

  it('BR-56: bulkInitiatePending latch disables re-entry during flush latency', async () => {
    let resolveFlush: ((v: ScheduleCommitResult | null) => void) | null = null;
    flushHeldSingle = () =>
      new Promise((resolve) => {
        resolveFlush = resolve;
      });

    const { result } = renderBulk();
    let first: Promise<void> | null = null;
    act(() => {
      first = result.current.initiateBulk();
    });
    // Sync latch before flush resolves
    expect(result.current.bulkInitiatePending).toBe(true);

    // Second initiate is a no-op while latch held
    await act(async () => {
      await result.current.initiateBulk();
    });

    await act(async () => {
      resolveFlush?.(null);
      await first;
    });
    expect(result.current.bulkInitiatePending).toBe(false);
    expect(result.current.bulk.phase).toBe('holding');
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

  it('UXW2-6: initiateBulkFromItems sequences pinned ids even when selection is empty', async () => {
    selectedIds = new Set();
    const { result } = renderBulk();

    await act(async () => {
      await result.current.initiateBulkFromItems([items.a, items.b]);
    });
    expect(result.current.bulk.phase).toBe('holding');
    expect(result.current.bulkHoldAnnounce).toBe('Saving 2… — Undo');
    expect(commitCalls).toEqual([]);

    await expireBulkHold();
    expect(commitCalls).toEqual(['a', 'b']);
    expect(recognitionApi.bulkAcceptSuggestions).not.toHaveBeenCalled();
  });

  it('UXW2-6: pinned group-accept items fire even when resolveItems would drop them', async () => {
    selectedIds = new Set();
    const { result } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange,
        resolveItems: () => [],
        flushHeldSingle,
        commitOne,
        heldSingleSuggestionId: null,
        setBulkActionActive,
        isBulkActiveRef,
        awaitBulkIdleOrFlushRef,
      }),
    );

    await act(async () => {
      await result.current.initiateBulkFromItems([items.a, items.c]);
    });
    await expireBulkHold();
    expect(commitCalls).toEqual(['a', 'c']);
  });

  it('UXW2-6: initiateBulkFromItems no-ops on an empty item list', async () => {
    const { result } = renderBulk();
    await act(async () => {
      await result.current.initiateBulkFromItems([]);
    });
    expect(result.current.bulk.phase).toBe('idle');
    expect(commitCalls).toEqual([]);
  });
});

describe('matrix M1 single / review-each / bulk (BR-51)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(recognitionApi.acceptSuggestion).mockReset();
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'x',
      resolution: 'accepted',
      identity_id: 'i',
      cluster_id: 'c',
      message: 'ok',
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('M1 SINGLE via scheduleAccept + flush → exact {id}', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const bulkActionRef = { current: false };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(
      () => useSuggestionReviewMutations({ queryClient, bulkActionRef }),
      { wrapper },
    );

    act(() => {
      void result.current.scheduleAccept('only-1');
    });
    expect(result.current.hold.phase).toBe('holding');
    expect(result.current.hold.suggestionId).toBe('only-1');
    expect(HOLD_STATUS_COPY).toContain('Undo');

    await act(async () => {
      await result.current.flushHeld();
    });

    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('only-1');
  });

  it('M1 REVIEW-EACH: N sequential single accept+flush cycles → ordered id set', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const bulkActionRef = { current: false };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(
      () => useSuggestionReviewMutations({ queryClient, bulkActionRef }),
      { wrapper },
    );

    const ids = ['r1', 'r2', 'r3'];
    for (const id of ids) {
      act(() => {
        void result.current.scheduleAccept(id);
      });
      await act(async () => {
        await result.current.flushHeld();
      });
    }

    const mutated = vi.mocked(recognitionApi.acceptSuggestion).mock.calls.map((c) => c[0]);
    expect(mutated).toEqual(ids);
    expect(mutated).toHaveLength(3);
  });

  it('M1 BULK: exact ordered id set via bulk sequencer', async () => {
    const commitCalls: string[] = [];
    let selectedIds = new Set(['b1', 'b2']);
    const isBulkActiveRef = { current: false };
    const awaitBulkIdleOrFlushRef: { current: (() => Promise<void>) | null } = {
      current: null,
    };

    const { result } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange: (next) => {
          selectedIds = next;
        },
        resolveItems: (ids) =>
          ids.map((id) => ({ suggestionId: id, commitKind: 'accept' as const, label: 'X' })),
        flushHeldSingle: () => Promise.resolve(null),
        commitOne: (_kind, id) => {
          commitCalls.push(id);
          return Promise.resolve('committed' as const);
        },
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
    expect(commitCalls).toEqual(['b1', 'b2']);
  });
});

describe('BR-49 chainRef circular wait + BR-48 person-commit bulk ordering', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(recognitionApi.acceptSuggestion).mockReset();
    vi.mocked(recognitionApi.acceptSuggestion).mockImplementation(
      (id: string) =>
        new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              suggestion_id: id,
              resolution: 'accepted',
              identity_id: `i-${id}`,
              cluster_id: 'c',
              message: 'ok',
            });
          }, 10);
        }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('BR-49: bulk hold open → single schedule during flush → both complete, no hang', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const bulkActionRef = { current: false };
    const awaitBulkIdleOrFlushRef: { current: (() => Promise<void>) | null } = {
      current: null,
    };
    const isBulkActiveRef = { current: false };

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result: mut } = renderHook(
      () =>
        useSuggestionReviewMutations({
          queryClient,
          bulkActionRef,
          awaitBulkIdleOrFlushRef,
          isBulkActiveRef,
        }),
      { wrapper },
    );

    let selectedIds = new Set(['bulk-a', 'bulk-b']);
    const bulkCommitCalls: string[] = [];

    const { result: bulk } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange: (next) => {
          selectedIds = next;
        },
        resolveItems: (ids) =>
          ids.map((id) => ({
            suggestionId: id,
            commitKind: 'accept' as const,
            label: 'L',
          })),
        flushHeldSingle: () => mut.current.flushHeld(),
        commitOne: async (kind, id) => {
          bulkCommitCalls.push(id);
          return mut.current.commitOneNow(kind, id);
        },
        heldSingleSuggestionId: mut.current.hold.suggestionId,
        setBulkActionActive: (active) => {
          bulkActionRef.current = active;
        },
        isBulkActiveRef,
        awaitBulkIdleOrFlushRef,
      }),
    );

    // Open bulk hold
    await act(async () => {
      await bulk.current.initiateBulk();
    });
    expect(bulk.current.bulk.phase).toBe('holding');
    expect(isBulkActiveRef.current).toBe(true);

    // Single schedule during bulk — must flush bulk first without deadlocking chainRef
    let singleResult: { outcome: string; suggestionId: string } | null = null;
    const singlePromise = act(async () => {
      const p = mut.current.scheduleAccept('single-x');
      // Advance bulk timer / sequence microtasks
      await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS);
      await vi.advanceTimersByTimeAsync(50);
      await Promise.resolve();
      await Promise.resolve();
      singleResult = await p;
    });

    await singlePromise;

    expect(bulkCommitCalls).toEqual(['bulk-a', 'bulk-b']);
    expect(singleResult).toMatchObject({ suggestionId: 'single-x' });
    // single opened hold after bulk — either holding or already committed via further flush
    expect(['holding', 'idle', 'committing', 'failed']).toContain(mut.current.hold.phase);
    // If still holding, flush it
    if (mut.current.hold.phase === 'holding') {
      await act(async () => {
        await mut.current.flushHeld();
        await vi.advanceTimersByTimeAsync(50);
      });
    }
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('single-x');
  }, 15_000);

  it('BR-48: person-commit during bulk hold flushes bulk first; no interleave', async () => {
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockReset();
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue({
      cluster_id: 'cluster-pc',
      roster_entry_id: 1,
      label: 'Alex',
    } as never);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const bulkActionRef = { current: false };
    const awaitBulkIdleOrFlushRef: { current: (() => Promise<void>) | null } = {
      current: null,
    };
    const isBulkActiveRef = { current: false };
    const order: string[] = [];

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result: mut } = renderHook(
      () =>
        useSuggestionReviewMutations({
          queryClient,
          bulkActionRef,
          awaitBulkIdleOrFlushRef,
          isBulkActiveRef,
        }),
      { wrapper },
    );

    let selectedIds = new Set(['pb-a', 'pb-b']);
    const { result: bulk } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange: (next) => {
          selectedIds = next;
        },
        resolveItems: (ids) =>
          ids.map((id) => ({
            suggestionId: id,
            commitKind: 'accept' as const,
            label: 'L',
          })),
        flushHeldSingle: () => mut.current.flushHeld(),
        commitOne: async (kind, id) => {
          order.push(`bulk:${id}`);
          const r = await mut.current.commitOneNow(kind, id);
          return r;
        },
        heldSingleSuggestionId: null,
        setBulkActionActive: (active) => {
          bulkActionRef.current = active;
        },
        isBulkActiveRef,
        awaitBulkIdleOrFlushRef,
      }),
    );

    await act(async () => {
      await bulk.current.initiateBulk();
    });
    expect(bulk.current.bulk.phase).toBe('holding');

    let personResult: { outcome: string } | null = null;
    await act(async () => {
      const p = mut.current.schedulePersonCommit({
        clusterId: 'cluster-pc',
        newEntryName: 'Alex',
      });
      await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS);
      await vi.advanceTimersByTimeAsync(50);
      await Promise.resolve();
      await Promise.resolve();
      personResult = await p;
      order.push(`person:${personResult.outcome}`);
    });

    expect(order[0]).toBe('bulk:pb-a');
    expect(order[1]).toBe('bulk:pb-b');
    expect(order[2]).toBe('person:committed');
    expect(personResult).toMatchObject({ outcome: 'committed' });
  }, 15_000);

  it('BR-48: person-commit during running sequence waits for completion; no interleave', async () => {
    const order: string[] = [];
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockReset();
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockImplementation(() => {
      order.push('person:post');
      return Promise.resolve({
        cluster_id: 'cluster-rs',
        roster_entry_id: 1,
        label: 'Alex',
      } as never);
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const bulkActionRef = { current: false };
    const awaitBulkIdleOrFlushRef: { current: (() => Promise<void>) | null } = {
      current: null,
    };
    const isBulkActiveRef = { current: false };

    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result: mut } = renderHook(
      () =>
        useSuggestionReviewMutations({
          queryClient,
          bulkActionRef,
          awaitBulkIdleOrFlushRef,
          isBulkActiveRef,
        }),
      { wrapper },
    );

    let selectedIds = new Set(['rs-a', 'rs-b']);
    const { result: bulk } = renderHook(() =>
      useBulkReviewCommit({
        selectedIds,
        onSelectedIdsChange: (next) => {
          selectedIds = next;
        },
        resolveItems: (ids) =>
          ids.map((id) => ({
            suggestionId: id,
            commitKind: 'accept' as const,
            label: 'L',
          })),
        flushHeldSingle: () => mut.current.flushHeld(),
        commitOne: async (kind, id) => {
          order.push(`bulk:${id}`);
          return mut.current.commitOneNow(kind, id);
        },
        heldSingleSuggestionId: null,
        setBulkActionActive: (active) => {
          bulkActionRef.current = active;
        },
        isBulkActiveRef,
        awaitBulkIdleOrFlushRef,
      }),
    );

    await act(async () => {
      await bulk.current.initiateBulk();
    });
    expect(bulk.current.bulk.phase).toBe('holding');

    // Expire hold WITHOUT resolving the 10ms POSTs → sequence is live (committing).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UNDO_HOLD_MS);
    });
    expect(order).toEqual(['bulk:rs-a']);
    expect(isBulkActiveRef.current).toBe(true);

    // Schedule person-commit mid-sequence — must wait for the whole sequence.
    let personResult: { outcome: string } | null = null;
    await act(async () => {
      const p = mut.current.schedulePersonCommit({
        clusterId: 'cluster-rs',
        newEntryName: 'Alex',
      });
      await vi.advanceTimersByTimeAsync(50);
      await Promise.resolve();
      await Promise.resolve();
      personResult = await p;
    });

    expect(order).toEqual(['bulk:rs-a', 'bulk:rs-b', 'person:post']);
    expect(personResult).toMatchObject({ outcome: 'committed' });
  }, 15_000);
});

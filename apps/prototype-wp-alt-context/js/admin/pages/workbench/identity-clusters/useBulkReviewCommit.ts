/**
 * E21-5 Slice 5 — multi-select bulk commit sequencer (PR-30 state machine).
 *
 * Explicit multi-select (default empty) → ONE bulk hold ("Saving N… — Undo") →
 * sequential per-id atomic POSTs, single-in-flight, stop-on-first-failure.
 * Zero calls to legacy bulk-accept. Reuses UNDO_HOLD_MS + pause mechanics.
 *
 * Bulk initiation flushes any held single commit first. A following single
 * action waits for this sequence via `awaitBulkIdleOrFlush` (wired into
 * useSuggestionReviewMutations). Unmount fires item 1 only + cancels remainder.
 */

import React from 'react';

import {
  UNDO_HOLD_MS,
  type ScheduleCommitResult,
  type SuggestionCommitKind,
} from './useSuggestionReviewMutations';

/** Bulk hold announce — N is the selection size at initiate time. */
export const bulkHoldStatusCopy = (count: number): string => `Saving ${count}… — Undo`;

/** PR-38: homogeneous label → "Accept N for <label>"; else "Accept N selected". */
export const bulkCommitLabel = (count: number, sharedLabel: string | null): string => {
  if (count <= 0) {
    return 'Accept 0 selected';
  }
  if (sharedLabel) {
    return `Accept ${count} for ${sharedLabel}`;
  }
  return `Accept ${count} selected`;
};

/** Shared label only when every selected item shares one non-empty target label. */
export const sharedSelectionLabel = (
  labels: readonly (string | null | undefined)[],
): string | null => {
  const normalized = labels.map((l) => (l && l.trim().length > 0 ? l.trim() : null));
  if (normalized.length === 0) {
    return null;
  }
  const first = normalized[0];
  if (!first) {
    return null;
  }
  return normalized.every((l) => l === first) ? first : null;
};

export type BulkCommitPhase = 'idle' | 'holding' | 'committing' | 'partial_failed';

export interface BulkCommitItem {
  suggestionId: string;
  commitKind: SuggestionCommitKind;
  /** Target person label for PR-38 / failure copy (may be null). */
  label: string | null;
}

export interface BulkPartialFailure {
  landed: number;
  failed: number;
  notAttempted: number;
  /** Label of the item that failed (if any). */
  failedLabel: string | null;
  /** Human message for role=alert. */
  message: string;
}

export interface BulkCommitState {
  phase: BulkCommitPhase;
  /** Snapshot of ids held at initiate (order preserved for sequential fire). */
  heldIds: readonly string[];
  /** Count announced in "Saving N…". */
  holdCount: number;
  partialFailure: BulkPartialFailure | null;
}

export type BulkCommitOneFn = (
  kind: SuggestionCommitKind,
  suggestionId: string,
) => Promise<'committed' | 'failed'>;

export interface UseBulkReviewCommitOptions {
  /** Current controlled selection (lifted to ScanTabContent). */
  selectedIds: ReadonlySet<string>;
  onSelectedIdsChange: (next: Set<string>) => void;
  /** Resolve queue metadata for selected ids (order = caller list order). */
  resolveItems: (ids: readonly string[]) => BulkCommitItem[];
  /** Flush any held single-item commit (§3). */
  flushHeldSingle: () => Promise<ScheduleCommitResult | null>;
  /** Fire one atomic per-id POST with cache side-effects (no hold UI). */
  commitOne: BulkCommitOneFn;
  /**
   * Suggestion id currently in a single-item hold/commit — cannot be selected
   * (and selected ids block single hold via isIdInBulkSelection on the host).
   */
  heldSingleSuggestionId: string | null;
  /**
   * Host sets bulkActionRef while sequence runs so per-id invalidation is
   * deferred; host invalidates once after bulk settles.
   */
  setBulkActionActive: (active: boolean) => void;
  /** Optional post-sequence invalidate (projection / media). */
  onBulkSequenceSettled?: () => void;
  /**
   * Written synchronously on phase change so scheduleCommit sees bulk busy
   * in the same turn (idle-path exclusion).
   */
  isBulkActiveRef: React.MutableRefObject<boolean>;
  /** Host assigns awaitBulkIdleOrFlush for single-commit busy path. */
  awaitBulkIdleOrFlushRef: React.MutableRefObject<(() => Promise<void>) | null>;
}

export interface UseBulkReviewCommitResult {
  bulk: BulkCommitState;
  bulkHoldAnnounce: string;
  commitLabelForSelection: string;
  sharedLabel: string | null;
  isBulkActive: boolean;
  isIdSelectable: (suggestionId: string) => boolean;
  isIdSelected: (suggestionId: string) => boolean;
  toggleSelect: (suggestionId: string) => void;
  clearSelection: () => void;
  /** Drop ids that left the projection; returns dropped count (for announce). */
  pruneMissingIds: (presentIds: ReadonlySet<string>) => number;
  initiateBulk: () => Promise<void>;
  undoBulk: () => void;
  setBulkHoldPaused: (paused: boolean) => void;
  /**
   * If holding: fire sequence. If committing: wait until idle.
   * Used by single scheduleCommit (bulk→single flush ordering).
   */
  awaitBulkIdleOrFlush: () => Promise<void>;
  /** Retry remainder (failed + unattempted still selected). */
  retryBulk: () => Promise<void>;
  clearPartialFailure: () => void;
}

interface HeldBulk {
  entryId: number;
  items: BulkCommitItem[];
  resolve: () => void;
  remainingMs: number;
  deadlineMs: number;
  paused: boolean;
  timerId: ReturnType<typeof setTimeout> | null;
  /** Cancel flag for remainder after unmount item-1 fire. */
  cancelled: boolean;
}

const buildPartialFailureMessage = (
  landed: number,
  total: number,
  failedLabel: string | null,
  notAttempted: number,
): string => {
  const labelBit = failedLabel ? ` — Accept failed for ${failedLabel}` : '';
  const remainderBit = notAttempted > 0 ? `; ${notAttempted} not attempted` : '';
  return `${landed} of ${total} accepted${labelBit}${remainderBit}`;
};

export const useBulkReviewCommit = ({
  selectedIds,
  onSelectedIdsChange,
  resolveItems,
  flushHeldSingle,
  commitOne,
  heldSingleSuggestionId,
  setBulkActionActive,
  onBulkSequenceSettled,
  isBulkActiveRef,
  awaitBulkIdleOrFlushRef,
}: UseBulkReviewCommitOptions): UseBulkReviewCommitResult => {
  const [bulk, setBulk] = React.useState<BulkCommitState>({
    phase: 'idle',
    heldIds: [],
    holdCount: 0,
    partialFailure: null,
  });

  const mountedRef = React.useRef(true);
  const heldBulkRef = React.useRef<HeldBulk | null>(null);
  const phaseRef = React.useRef<BulkCommitPhase>('idle');
  const sequencePromiseRef = React.useRef<Promise<void> | null>(null);
  const nextEntryIdRef = React.useRef(1);
  const idleWaitersRef = React.useRef<(() => void)[]>([]);
  const selectedIdsRef = React.useRef(selectedIds);
  selectedIdsRef.current = selectedIds;
  const onSelectedIdsChangeRef = React.useRef(onSelectedIdsChange);
  onSelectedIdsChangeRef.current = onSelectedIdsChange;
  const commitOneRef = React.useRef(commitOne);
  commitOneRef.current = commitOne;
  const setBulkActionActiveRef = React.useRef(setBulkActionActive);
  setBulkActionActiveRef.current = setBulkActionActive;
  const onBulkSequenceSettledRef = React.useRef(onBulkSequenceSettled);
  onBulkSequenceSettledRef.current = onBulkSequenceSettled;

  const setBulkSafe = React.useCallback(
    (next: BulkCommitState) => {
      phaseRef.current = next.phase;
      isBulkActiveRef.current = next.phase === 'holding' || next.phase === 'committing';
      if (mountedRef.current) {
        setBulk(next);
      }
    },
    [isBulkActiveRef],
  );

  const notifyIdle = React.useCallback(() => {
    const waiters = idleWaitersRef.current;
    idleWaitersRef.current = [];
    for (const w of waiters) {
      w();
    }
  }, []);

  const clearHeldTimer = React.useCallback(() => {
    const held = heldBulkRef.current;
    if (held?.timerId != null) {
      clearTimeout(held.timerId);
      held.timerId = null;
    }
  }, []);

  const dropFromSelection = React.useCallback((id: string): void => {
    const current = selectedIdsRef.current;
    if (!current.has(id)) {
      return;
    }
    const next = new Set(current);
    next.delete(id);
    selectedIdsRef.current = next;
    onSelectedIdsChangeRef.current(next);
  }, []);

  const selectedLabels = React.useMemo(() => {
    const items = resolveItems([...selectedIds]);
    return items.map((i) => i.label);
  }, [resolveItems, selectedIds]);

  const sharedLabel = React.useMemo(
    () => sharedSelectionLabel(selectedLabels),
    [selectedLabels],
  );

  const commitLabelForSelection = React.useMemo(
    () => bulkCommitLabel(selectedIds.size, sharedLabel),
    [selectedIds.size, sharedLabel],
  );

  const isBulkActive = bulk.phase === 'holding' || bulk.phase === 'committing';

  const isIdSelected = React.useCallback(
    (suggestionId: string) => selectedIds.has(suggestionId),
    [selectedIds],
  );

  const isIdSelectable = React.useCallback(
    (suggestionId: string): boolean => {
      // In-hold single id cannot be selected (PR-30 overlap).
      if (heldSingleSuggestionId != null && heldSingleSuggestionId === suggestionId) {
        return false;
      }
      // During bulk hold/commit, freeze selection toggles.
      if (phaseRef.current === 'holding' || phaseRef.current === 'committing') {
        return false;
      }
      return true;
    },
    [heldSingleSuggestionId],
  );

  const toggleSelect = React.useCallback(
    (suggestionId: string): void => {
      if (!isIdSelectable(suggestionId)) {
        return;
      }
      const next = new Set(selectedIds);
      if (next.has(suggestionId)) {
        next.delete(suggestionId);
      } else {
        next.add(suggestionId);
      }
      onSelectedIdsChange(next);
    },
    [isIdSelectable, onSelectedIdsChange, selectedIds],
  );

  const clearSelection = React.useCallback((): void => {
    onSelectedIdsChange(new Set());
  }, [onSelectedIdsChange]);

  const pruneMissingIds = React.useCallback(
    (presentIds: ReadonlySet<string>): number => {
      if (selectedIds.size === 0) {
        return 0;
      }
      let dropped = 0;
      const next = new Set<string>();
      for (const id of selectedIds) {
        if (presentIds.has(id)) {
          next.add(id);
        } else {
          dropped += 1;
        }
      }
      if (dropped > 0) {
        onSelectedIdsChange(next);
      }
      return dropped;
    },
    [onSelectedIdsChange, selectedIds],
  );

  /**
   * Sequential per-id POSTs. `limitToFirstOnly` = unmount policy (item 1 only).
   * Drops committed ids from selection as each POST succeeds (PA-27).
   */
  const runSequence = React.useCallback(
    async (
      items: BulkCommitItem[],
      options: { limitToFirstOnly: boolean; updateUi: boolean },
    ): Promise<void> => {
      if (items.length === 0) {
        setBulkSafe({
          phase: 'idle',
          heldIds: [],
          holdCount: 0,
          partialFailure: null,
        });
        notifyIdle();
        return;
      }

      setBulkActionActiveRef.current(true);
      if (options.updateUi) {
        setBulkSafe({
          phase: 'committing',
          heldIds: items.map((i) => i.suggestionId),
          holdCount: items.length,
          partialFailure: null,
        });
      }

      let landed = 0;
      let failedLabel: string | null = null;
      let failedIndex = -1;
      const total = items.length;
      const toRun = options.limitToFirstOnly ? items.slice(0, 1) : items;

      try {
        for (let i = 0; i < toRun.length; i += 1) {
          const held = heldBulkRef.current;
          if (held?.cancelled && i > 0) {
            break;
          }
          const item = toRun[i];
          const outcome = await commitOneRef.current(item.commitKind, item.suggestionId);
          if (outcome === 'committed') {
            landed += 1;
            dropFromSelection(item.suggestionId);
          } else {
            failedIndex = i;
            failedLabel = item.label;
            break;
          }
        }
      } finally {
        setBulkActionActiveRef.current(false);
        onBulkSequenceSettledRef.current?.();
      }

      if (!mountedRef.current) {
        notifyIdle();
        return;
      }

      if (options.limitToFirstOnly) {
        setBulkSafe({
          phase: 'idle',
          heldIds: [],
          holdCount: 0,
          partialFailure: null,
        });
        notifyIdle();
        return;
      }

      if (failedIndex >= 0) {
        const notAttempted = total - failedIndex - 1;
        setBulkSafe({
          phase: 'partial_failed',
          heldIds: [],
          holdCount: 0,
          partialFailure: {
            landed,
            failed: 1,
            notAttempted,
            failedLabel,
            message: buildPartialFailureMessage(landed, total, failedLabel, notAttempted),
          },
        });
        notifyIdle();
        return;
      }

      setBulkSafe({
        phase: 'idle',
        heldIds: [],
        holdCount: 0,
        partialFailure: null,
      });
      notifyIdle();
    },
    [dropFromSelection, notifyIdle, setBulkSafe],
  );

  const fireHeldBulk = React.useCallback(
    async (options: { limitToFirstOnly: boolean; updateUi: boolean }): Promise<void> => {
      const held = heldBulkRef.current;
      if (!held) {
        return;
      }
      clearHeldTimer();
      heldBulkRef.current = null;
      const items = held.items;
      held.resolve();
      const run = runSequence(items, options);
      sequencePromiseRef.current = run;
      await run;
      sequencePromiseRef.current = null;
    },
    [clearHeldTimer, runSequence],
  );

  const armBulkTimer = React.useCallback(() => {
    const held = heldBulkRef.current;
    if (!held || held.paused) {
      return;
    }
    clearHeldTimer();
    held.deadlineMs = Date.now() + held.remainingMs;
    const entryId = held.entryId;
    held.timerId = setTimeout(() => {
      void (async () => {
        if (heldBulkRef.current?.entryId !== entryId) {
          return;
        }
        await fireHeldBulk({ limitToFirstOnly: false, updateUi: true });
      })();
    }, held.remainingMs);
  }, [clearHeldTimer, fireHeldBulk]);

  const openBulkHold = React.useCallback(
    (items: BulkCommitItem[]): void => {
      if (!mountedRef.current || items.length === 0) {
        return;
      }
      const entry: HeldBulk = {
        entryId: nextEntryIdRef.current++,
        items,
        resolve: () => undefined,
        remainingMs: UNDO_HOLD_MS,
        deadlineMs: Date.now() + UNDO_HOLD_MS,
        paused: false,
        timerId: null,
        cancelled: false,
      };
      heldBulkRef.current = entry;
      setBulkSafe({
        phase: 'holding',
        heldIds: items.map((i) => i.suggestionId),
        holdCount: items.length,
        partialFailure: null,
      });
      armBulkTimer();
    },
    [armBulkTimer, setBulkSafe],
  );

  const initiateBulk = React.useCallback(async (): Promise<void> => {
    if (phaseRef.current === 'holding' || phaseRef.current === 'committing') {
      return;
    }
    if (selectedIds.size === 0) {
      return;
    }

    const items = resolveItems([...selectedIds]);
    if (items.length === 0) {
      return;
    }

    // First flushes any held single commit (PR-30).
    const prior = await flushHeldSingle();
    if (prior?.outcome === 'failed') {
      return;
    }

    if (!mountedRef.current) {
      return;
    }

    // Open hold synchronously — do not await the hold lifetime (same model as scheduleCommit).
    openBulkHold(items);
  }, [flushHeldSingle, openBulkHold, resolveItems, selectedIds]);

  const undoBulk = React.useCallback((): void => {
    const held = heldBulkRef.current;
    if (!held || phaseRef.current !== 'holding') {
      return;
    }
    clearHeldTimer();
    heldBulkRef.current = null;
    held.cancelled = true;
    held.resolve();
    setBulkSafe({
      phase: 'idle',
      heldIds: [],
      holdCount: 0,
      partialFailure: null,
    });
    notifyIdle();
  }, [clearHeldTimer, notifyIdle, setBulkSafe]);

  const setBulkHoldPaused = React.useCallback(
    (paused: boolean): void => {
      const held = heldBulkRef.current;
      if (!held || phaseRef.current !== 'holding') {
        return;
      }
      if (paused === held.paused) {
        return;
      }
      if (paused) {
        if (held.timerId != null) {
          held.remainingMs = Math.max(0, held.deadlineMs - Date.now());
          clearHeldTimer();
        }
        held.paused = true;
      } else {
        held.paused = false;
        armBulkTimer();
      }
    },
    [armBulkTimer, clearHeldTimer],
  );

  const awaitBulkIdleOrFlush = React.useCallback(async (): Promise<void> => {
    if (phaseRef.current === 'holding' && heldBulkRef.current) {
      await fireHeldBulk({ limitToFirstOnly: false, updateUi: true });
      return;
    }
    if (phaseRef.current === 'committing' || sequencePromiseRef.current) {
      if (sequencePromiseRef.current) {
        await sequencePromiseRef.current;
        return;
      }
      await new Promise<void>((resolve) => {
        idleWaitersRef.current.push(resolve);
      });
    }
  }, [fireHeldBulk]);

  // Keep host ref current every render (scheduleCommit reads .current).
  awaitBulkIdleOrFlushRef.current = awaitBulkIdleOrFlush;
  isBulkActiveRef.current = bulk.phase === 'holding' || bulk.phase === 'committing';

  const retryBulk = React.useCallback(async (): Promise<void> => {
    if (selectedIds.size === 0) {
      return;
    }
    await initiateBulk();
  }, [initiateBulk, selectedIds.size]);

  const clearPartialFailure = React.useCallback((): void => {
    if (bulk.phase === 'partial_failed') {
      setBulkSafe({
        phase: 'idle',
        heldIds: [],
        holdCount: 0,
        partialFailure: null,
      });
    }
  }, [bulk.phase, setBulkSafe]);

  // Unmount: fire item 1 only; cancel remainder (PR-30).
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const held = heldBulkRef.current;
      if (!held) {
        return;
      }
      clearHeldTimer();
      heldBulkRef.current = null;
      held.cancelled = true;
      held.resolve();
      const first = held.items[0];
      if (first) {
        setBulkActionActiveRef.current(true);
        void commitOneRef.current(first.commitKind, first.suggestionId).finally(() => {
          setBulkActionActiveRef.current(false);
          onBulkSequenceSettledRef.current?.();
        });
      }
    };
  }, [clearHeldTimer]);

  const bulkHoldAnnounce =
    bulk.phase === 'holding' || bulk.phase === 'committing'
      ? bulkHoldStatusCopy(bulk.holdCount)
      : '';

  return {
    bulk,
    bulkHoldAnnounce,
    commitLabelForSelection,
    sharedLabel,
    isBulkActive,
    isIdSelectable,
    isIdSelected,
    toggleSelect,
    clearSelection,
    pruneMissingIds,
    initiateBulk,
    undoBulk,
    setBulkHoldPaused,
    awaitBulkIdleOrFlush,
    retryBulk,
    clearPartialFailure,
  };
};

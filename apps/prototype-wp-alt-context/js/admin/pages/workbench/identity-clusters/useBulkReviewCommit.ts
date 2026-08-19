/**
 * E21-5 Slice 5 — multi-select bulk commit sequencer (PR-30 state machine).
 *
 * Explicit multi-select (default empty) → ONE bulk hold ("Saving N… — Undo") →
 * sequential per-id atomic POSTs, single-in-flight, stop-on-first-failure.
 * Zero calls to legacy bulk-accept. Reuses UNDO_HOLD_MS + pause mechanics.
 *
 * Bulk initiation flushes any held single commit first. A following single
 * action waits for this sequence via `awaitBulkIdleOrFlush` (wired into
 * useSuggestionReviewMutations — pre-enqueue, never inside chainRef).
 * Unmount: holding → fire item 1 only; committing → cancel remainder after
 * in-flight POST (live sequence-state ref).
 */

import React from 'react';

import {
  UNDO_HOLD_MS,
  type ScheduleCommitResult,
  type SuggestionCommitKind,
} from './useSuggestionReviewMutations';

/** Bulk hold announce — N is the selection size at initiate time. Holding only. */
export const bulkHoldStatusCopy = (count: number): string => `Saving ${count}… — Undo`;

/** BR-55: committing phase drops Undo suffix (Undo unreachable). */
export const bulkCommittingStatusCopy = (count: number): string => `Saving ${count}…`;

/**
 * PA-27 partial-failure copy — single pinned structure (BR-53).
 * Banned soft fillers: "some", "several", "a few", "failed to save".
 */
export const buildPartialFailureMessage = (
  landed: number,
  total: number,
  failedLabel: string | null,
  notAttempted: number,
): string => {
  const label = failedLabel && failedLabel.trim().length > 0 ? failedLabel.trim() : 'item';
  return `${landed} of ${total} accepted — 'Accept' failed for ${label}; ${notAttempted} not attempted`;
};

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

/** Canonical bulk commit phases [sr-007]. */
export const BULK_COMMIT_PHASE = {
  IDLE: 'idle',
  HOLDING: 'holding',
  COMMITTING: 'committing',
  PARTIAL_FAILED: 'partial_failed',
} as const;

export type BulkCommitPhase = (typeof BULK_COMMIT_PHASE)[keyof typeof BULK_COMMIT_PHASE];

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
  /**
   * BR-56: true from initiate/retry click until hold opens or early-return.
   * Disables the initiating control from the same sync signal.
   */
  bulkInitiatePending: boolean;
  isIdSelectable: (suggestionId: string) => boolean;
  isIdSelected: (suggestionId: string) => boolean;
  /** BR-47: true when id is in the multi-select set (blocks single Accept/Reject). */
  isIdInBulkSelection: (suggestionId: string) => boolean;
  toggleSelect: (suggestionId: string) => void;
  clearSelection: () => void;
  /** Drop ids that left the projection; returns dropped count (for announce). */
  pruneMissingIds: (presentIds: ReadonlySet<string>) => number;
  initiateBulk: () => Promise<void>;
  /**
   * Group-accept path: hold+sequence an explicit item list, ignoring the
   * current selection ∩ filter intersection (the ids are already the group).
   */
  initiateBulkFromItems: (items: readonly BulkCommitItem[]) => Promise<void>;
  undoBulk: () => void;
  setBulkHoldPaused: (paused: boolean) => void;
  /**
   * If holding: fire sequence. If committing: wait until idle.
   * Used by single scheduleCommit (bulk→single flush ordering) — MUST be
   * awaited outside chainRef (BR-49), never from a chain link.
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
  /** Skip live selection ∩ filter re-cut at fire time (group-accept ids). */
  pinItems: boolean;
}

/** BR-46: live sequence state the loop and unmount cleanup share. */
interface RunningSequence {
  items: BulkCommitItem[];
  /** Index of the item currently in flight (or about to start). */
  index: number;
  cancelled: boolean;
}

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
    phase: BULK_COMMIT_PHASE.IDLE,
    heldIds: [],
    holdCount: 0,
    partialFailure: null,
  });
  /** BR-56: sync latch for initiate/retry — disables control before phase flips. */
  const [bulkInitiatePending, setBulkInitiatePending] = React.useState(false);

  const mountedRef = React.useRef(true);
  const heldBulkRef = React.useRef<HeldBulk | null>(null);
  const phaseRef = React.useRef<BulkCommitPhase>(BULK_COMMIT_PHASE.IDLE);
  const sequencePromiseRef = React.useRef<Promise<void> | null>(null);
  const runningSequenceRef = React.useRef<RunningSequence | null>(null);
  const nextEntryIdRef = React.useRef(1);
  const idleWaitersRef = React.useRef<(() => void)[]>([]);
  const bulkInitiateInFlightRef = React.useRef(false);
  /**
   * S3-02/GROK-03: the promise of an in-flight initiateBulk (flushing the held single,
   * about to open the bulk hold). Phase is still 'idle' during this window, so
   * awaitBulkIdleOrFlush must await THIS before checking holding/committing — else a
   * concurrent single interleaves with the opening bulk (TOCTOU on the pending gate).
   */
  const initiatePromiseRef = React.useRef<Promise<void> | null>(null);
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
  const resolveItemsRef = React.useRef(resolveItems);
  resolveItemsRef.current = resolveItems;
  const flushHeldSingleRef = React.useRef(flushHeldSingle);
  flushHeldSingleRef.current = flushHeldSingle;

  const setBulkSafe = React.useCallback(
    (next: BulkCommitState) => {
      phaseRef.current = next.phase;
      isBulkActiveRef.current = next.phase === BULK_COMMIT_PHASE.HOLDING || next.phase === BULK_COMMIT_PHASE.COMMITTING;
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

  // M2: resolveItems may drop ids outside active KIND∩band filters — label
  // and commit size follow the resolved set, not the raw selection size.
  const resolvedSelection = React.useMemo(
    () => resolveItems([...selectedIds]),
    [resolveItems, selectedIds],
  );

  const selectedLabels = React.useMemo(
    () => resolvedSelection.map((i) => i.label),
    [resolvedSelection],
  );

  const sharedLabel = React.useMemo(
    () => sharedSelectionLabel(selectedLabels),
    [selectedLabels],
  );

  const commitLabelForSelection = React.useMemo(
    () => bulkCommitLabel(resolvedSelection.length, sharedLabel),
    [resolvedSelection.length, sharedLabel],
  );

  const isBulkActive = bulk.phase === BULK_COMMIT_PHASE.HOLDING || bulk.phase === BULK_COMMIT_PHASE.COMMITTING;

  const isIdSelected = React.useCallback(
    (suggestionId: string) => selectedIds.has(suggestionId),
    [selectedIds],
  );

  /** BR-47: selection membership blocks single-item Accept/Reject hold. */
  const isIdInBulkSelection = React.useCallback(
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
      if (phaseRef.current === BULK_COMMIT_PHASE.HOLDING || phaseRef.current === BULK_COMMIT_PHASE.COMMITTING) {
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
   * Sequential per-id POSTs. `limitToFirstOnly` = unmount-while-holding policy.
   * Drops committed ids from selection as each POST succeeds (PA-27).
   * BR-46: checks live runningSequenceRef.cancelled each iteration.
   */
  const runSequence = React.useCallback(
    async (
      items: BulkCommitItem[],
      options: { limitToFirstOnly: boolean; updateUi: boolean },
    ): Promise<void> => {
      if (items.length === 0) {
        setBulkSafe({
          phase: BULK_COMMIT_PHASE.IDLE,
          heldIds: [],
          holdCount: 0,
          partialFailure: null,
        });
        notifyIdle();
        return;
      }

      const sequence: RunningSequence = {
        items,
        index: 0,
        cancelled: false,
      };
      runningSequenceRef.current = sequence;

      setBulkActionActiveRef.current(true);
      if (options.updateUi) {
        setBulkSafe({
          phase: BULK_COMMIT_PHASE.COMMITTING,
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
          // BR-46: unmount (or cancel) stops further items; in-flight finishes.
          if (sequence.cancelled) {
            break;
          }
          sequence.index = i;
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
        runningSequenceRef.current = null;
        setBulkActionActiveRef.current(false);
        onBulkSequenceSettledRef.current?.();
      }

      if (!mountedRef.current) {
        notifyIdle();
        return;
      }

      if (options.limitToFirstOnly || sequence.cancelled) {
        // Unmount cancel or hold-only first item: rest stay selected; idle chrome.
        setBulkSafe({
          phase: BULK_COMMIT_PHASE.IDLE,
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
          phase: BULK_COMMIT_PHASE.PARTIAL_FAILED,
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
        phase: BULK_COMMIT_PHASE.IDLE,
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
      // BR-50: re-filter snapshot against live selection at fire time (prune during hold).
      // pruneMissingIds keeps selection honest, so intersection drops pruned ids.
      // Pinned group-accept lists skip the live selection ∩ filter re-cut — those
      // ids are the explicit write set, not a tray selection.
      const live = selectedIdsRef.current;
      const stillSelected = held.pinItems
        ? held.items
        : held.items.filter((i) => live.has(i.suggestionId));
      // BR-62: also re-resolve against current filters at fire time — a URL-driven
      // KIND/band change during the hold narrows the fired set to the live
      // selection ∩ filters intersection (never wider than the current view).
      const allowedNow = held.pinItems
        ? new Set(stillSelected.map((i) => i.suggestionId))
        : new Set(
            resolveItemsRef.current(stillSelected.map((i) => i.suggestionId)).map(
              (i) => i.suggestionId,
            ),
          );
      const filtered = stillSelected.filter((i) => allowedNow.has(i.suggestionId));
      const items = options.limitToFirstOnly ? filtered.slice(0, 1) : filtered;
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
    (items: BulkCommitItem[], pinItems = false): void => {
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
        pinItems,
      };
      heldBulkRef.current = entry;
      setBulkSafe({
        phase: BULK_COMMIT_PHASE.HOLDING,
        heldIds: items.map((i) => i.suggestionId),
        holdCount: items.length,
        partialFailure: null,
      });
      armBulkTimer();
    },
    [armBulkTimer, setBulkSafe],
  );

  const clearBulkInitiateLatch = React.useCallback((): void => {
    bulkInitiateInFlightRef.current = false;
    if (mountedRef.current) {
      setBulkInitiatePending(false);
    }
  }, []);

  const initiateBulk = React.useCallback(async (): Promise<void> => {
    // BR-56: sync re-entry latch (personCommitInFlightRef pattern).
    if (bulkInitiateInFlightRef.current) {
      return;
    }
    if (phaseRef.current === BULK_COMMIT_PHASE.HOLDING || phaseRef.current === BULK_COMMIT_PHASE.COMMITTING) {
      return;
    }
    if (selectedIdsRef.current.size === 0) {
      return;
    }

    bulkInitiateInFlightRef.current = true;
    // S3-02/GROK-03: mark bulk active SYNCHRONOUSLY at latch-arm (not only via the
    // render-body OR of bulkInitiatePending). A same-turn scheduleCommit fired before the
    // re-render would otherwise still read isBulkActiveRef.current===false, take the idle
    // openHold path, and skip awaitBulk entirely. Next render recomputes it from phase.
    isBulkActiveRef.current = true;
    if (mountedRef.current) {
      setBulkInitiatePending(true);
    }

    // S3-02/GROK-03: publish the initiation promise BEFORE the first await so a concurrent
    // awaitBulkIdleOrFlush (single/person busy path) can serialize behind it. The IIFE runs
    // synchronously up to `await flushHeldSingle`, and no await sits between setting the
    // in-flight latch and assigning this ref, so both are visible atomically to waiters.
    const run = (async (): Promise<void> => {
      try {
        // Snapshot after latch; re-resolve post-flush (BR-47).
        const prior = await flushHeldSingleRef.current();
        if (prior?.outcome === 'failed') {
          return;
        }

        if (!mountedRef.current) {
          return;
        }

        // BR-47(a): drop the just-committed single id from selection + items.
        if (prior?.outcome === 'committed') {
          dropFromSelection(prior.suggestionId);
        }

        const liveIds = [...selectedIdsRef.current];
        let items = resolveItemsRef.current(liveIds);
        if (prior?.outcome === 'committed') {
          items = items.filter((i) => i.suggestionId !== prior.suggestionId);
        }
        if (items.length === 0) {
          return;
        }

        // Open hold synchronously — do not await the hold lifetime.
        openBulkHold(items);
      } finally {
        clearBulkInitiateLatch();
        initiatePromiseRef.current = null;
      }
    })();
    initiatePromiseRef.current = run;
    await run;
  }, [clearBulkInitiateLatch, dropFromSelection, openBulkHold]);

  const initiateBulkFromItems = React.useCallback(
    async (items: readonly BulkCommitItem[]): Promise<void> => {
      if (bulkInitiateInFlightRef.current) {
        return;
      }
      if (
        phaseRef.current === BULK_COMMIT_PHASE.HOLDING ||
        phaseRef.current === BULK_COMMIT_PHASE.COMMITTING
      ) {
        return;
      }
      if (items.length === 0) {
        return;
      }

      bulkInitiateInFlightRef.current = true;
      isBulkActiveRef.current = true;
      if (mountedRef.current) {
        setBulkInitiatePending(true);
      }

      const snapshot = items.map((item) => ({ ...item }));
      const run = (async (): Promise<void> => {
        try {
          const prior = await flushHeldSingleRef.current();
          if (prior?.outcome === 'failed') {
            return;
          }

          if (!mountedRef.current) {
            return;
          }

          if (prior?.outcome === 'committed') {
            dropFromSelection(prior.suggestionId);
          }

          let nextItems = snapshot;
          if (prior?.outcome === 'committed') {
            nextItems = snapshot.filter((i) => i.suggestionId !== prior.suggestionId);
          }
          if (nextItems.length === 0) {
            return;
          }

          openBulkHold(nextItems, true);
        } finally {
          clearBulkInitiateLatch();
          initiatePromiseRef.current = null;
        }
      })();
      initiatePromiseRef.current = run;
      await run;
    },
    [clearBulkInitiateLatch, dropFromSelection, openBulkHold],
  );

  const undoBulk = React.useCallback((): void => {
    const held = heldBulkRef.current;
    if (!held || phaseRef.current !== BULK_COMMIT_PHASE.HOLDING) {
      return;
    }
    clearHeldTimer();
    heldBulkRef.current = null;
    held.resolve();
    setBulkSafe({
      phase: BULK_COMMIT_PHASE.IDLE,
      heldIds: [],
      holdCount: 0,
      partialFailure: null,
    });
    notifyIdle();
  }, [clearHeldTimer, notifyIdle, setBulkSafe]);

  const setBulkHoldPaused = React.useCallback(
    (paused: boolean): void => {
      const held = heldBulkRef.current;
      if (!held || phaseRef.current !== BULK_COMMIT_PHASE.HOLDING) {
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
    // S3-02/GROK-03: an initiate is mid-flush (phase still 'idle', hold not yet open).
    // Wait for it to settle before inspecting phase, otherwise this returns a no-op and
    // the caller's single/person commit interleaves with the opening bulk sequence.
    const pendingInitiate = initiatePromiseRef.current;
    if (pendingInitiate) {
      // Swallow an initiation failure: awaitBulk must resolve to a deterministic phase
      // check, never reject into the caller's commit path. run's finally clears state.
      try {
        await pendingInitiate;
      } catch {
        // Initiation errored (no hold opened) — fall through; phase is idle → no-op.
      }
    }
    if (phaseRef.current === BULK_COMMIT_PHASE.HOLDING && heldBulkRef.current) {
      await fireHeldBulk({ limitToFirstOnly: false, updateUi: true });
      return;
    }
    if (phaseRef.current === BULK_COMMIT_PHASE.COMMITTING || sequencePromiseRef.current) {
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
  isBulkActiveRef.current =
    bulk.phase === BULK_COMMIT_PHASE.HOLDING ||
    bulk.phase === BULK_COMMIT_PHASE.COMMITTING ||
    bulkInitiatePending;

  const retryBulk = React.useCallback(async (): Promise<void> => {
    if (selectedIdsRef.current.size === 0) {
      return;
    }
    await initiateBulk();
  }, [initiateBulk]);

  const clearPartialFailure = React.useCallback((): void => {
    if (bulk.phase === BULK_COMMIT_PHASE.PARTIAL_FAILED) {
      setBulkSafe({
        phase: BULK_COMMIT_PHASE.IDLE,
        heldIds: [],
        holdCount: 0,
        partialFailure: null,
      });
    }
  }, [bulk.phase, setBulkSafe]);

  // Unmount: holding → fire item 1 only; committing → cancel remainder (BR-46).
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const running = runningSequenceRef.current;
      if (running) {
        // In-flight POST finishes; loop breaks before next item.
        running.cancelled = true;
        return;
      }
      const held = heldBulkRef.current;
      if (!held) {
        return;
      }
      clearHeldTimer();
      heldBulkRef.current = null;
      held.resolve();
      // BR-50/BR-62: unmount flush re-filters against live selection + filters (was raw items[0])
      // Pinned group-accept lists skip that re-cut so the explicit write set still fires.
      const live = selectedIdsRef.current;
      const stillSelected = held.pinItems
        ? held.items
        : held.items.filter((i) => live.has(i.suggestionId));
      const allowedNow = held.pinItems
        ? new Set(stillSelected.map((i) => i.suggestionId))
        : new Set(
            resolveItemsRef.current(stillSelected.map((i) => i.suggestionId)).map(
              (i) => i.suggestionId,
            ),
          );
      const first = stillSelected.find((i) => allowedNow.has(i.suggestionId));
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
    bulk.phase === BULK_COMMIT_PHASE.HOLDING
      ? bulkHoldStatusCopy(bulk.holdCount)
      : bulk.phase === BULK_COMMIT_PHASE.COMMITTING
        ? bulkCommittingStatusCopy(bulk.holdCount)
        : '';

  return {
    bulk,
    bulkHoldAnnounce,
    commitLabelForSelection,
    sharedLabel,
    isBulkActive,
    bulkInitiatePending,
    isIdSelectable,
    isIdSelected,
    isIdInBulkSelection,
    toggleSelect,
    clearSelection,
    pruneMissingIds,
    initiateBulk,
    initiateBulkFromItems,
    undoBulk,
    setBulkHoldPaused,
    awaitBulkIdleOrFlush,
    retryBulk,
    clearPartialFailure,
  };
};

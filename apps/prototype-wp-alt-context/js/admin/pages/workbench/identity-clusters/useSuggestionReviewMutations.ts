/**
 * E21-5 Slice 2 — immediate-commit accept/reject with gated advance + announced undo.
 *
 * Accept/reject opens a pre-commit hold (UNDO_HOLD_MS). The single atomic POST fires
 * only when the window closes, the next action flushes, or the host unmounts. Cache
 * removal and queue advance happen only on backend success — never optimistically.
 */

import React from 'react';
import { useMutation, type QueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import type {
  PendingMergeSuggestion,
  PendingMergeSuggestionsResponse,
  PendingNameSuggestionsResponse,
} from '../../../api/recognition/types';
import {
  acceptMergeSuggestion,
  acceptNameSuggestion,
  acceptSuggestion,
  bulkAcceptSuggestions,
  rejectMergeSuggestion,
  rejectNameSuggestion,
  rejectSuggestion,
} from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { useOptionalMergeSurvivors } from './MergeSurvivorContext';
import { PERSON_COMMIT_FAILURE_COPY } from './personCommitCopy';
import { authoritativeMergeSurvivor, resolveMergeSurvivorFromResponse } from './resolveMergeSurvivor';
import {
  dropClusterFromReviewCaches,
  invalidateReviewCachesWithoutRefetch,
  invalidateSuggestionProjection,
  REVIEW_DROP_MODE,
} from './suggestionProjection';
import type { SuggestionReviewPage } from './useSuggestionReviewQueries';

/** Pinned undo hold window — unit, e2e, and AT scripts share this single constant. */
export const UNDO_HOLD_MS = 5000;

/** Single hold/status copy — component + tests consume this export (BR-24). */
export const HOLD_STATUS_COPY = 'Saving… — Undo';

/** BR-55: committing phase drops Undo suffix (Undo unreachable). */
export const HOLD_COMMITTING_STATUS_COPY = 'Saving…';

export type SuggestionCommitKind =
  | 'accept'
  | 'reject'
  | 'acceptMerge'
  | 'rejectMerge'
  | 'acceptName'
  | 'rejectName';

/** Canonical single-hold commit phases [sr-007]. */
export const COMMIT_HOLD_PHASE = {
  IDLE: 'idle',
  HOLDING: 'holding',
  COMMITTING: 'committing',
  FAILED: 'failed',
} as const;

export type CommitHoldPhase = (typeof COMMIT_HOLD_PHASE)[keyof typeof COMMIT_HOLD_PHASE];

export interface CommitHoldState {
  phase: CommitHoldPhase;
  kind: SuggestionCommitKind | null;
  suggestionId: string | null;
  /** User-facing failure copy when phase === FAILED. */
  errorMessage: string | null;
}

export type ScheduleCommitOutcome =
  | 'committed'
  | 'undone'
  | 'failed'
  | 'not_attempted_prior_failed';

export interface ScheduleCommitResult {
  outcome: ScheduleCommitOutcome;
  kind: SuggestionCommitKind;
  suggestionId: string;
}

/**
 * Slice 3 person-commit — fires immediately after flushing any held accept/reject
 * (no undo window; deliberate multi-step Confirm). Single-in-flight via chainRef.
 */
/** Canonical person-commit phases [sr-007]. */
export const PERSON_COMMIT_PHASE = {
  IDLE: 'idle',
  COMMITTING: 'committing',
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',
} as const;

export type PersonCommitPhase = (typeof PERSON_COMMIT_PHASE)[keyof typeof PERSON_COMMIT_PHASE];

export interface PersonCommitState {
  phase: PersonCommitPhase;
  clusterId: string | null;
  errorMessage: string | null;
}

export interface PersonCommitRequest {
  clusterId: string;
  rosterEntryId?: number;
  newEntryName?: string;
}

export type PersonCommitOutcome = 'committed' | 'failed' | 'not_attempted_prior_failed';

export interface PersonCommitResult {
  outcome: PersonCommitOutcome;
  clusterId: string;
}

interface UseSuggestionReviewMutationsOptions {
  queryClient: QueryClient;
  bulkActionRef: React.MutableRefObject<boolean>;
  /**
   * Slice-5 bulk coordinator: when a single action is scheduled, flush/wait
   * any bulk hold/sequence first (PR-30 bulk→single ordering).
   */
  awaitBulkIdleOrFlushRef?: React.MutableRefObject<(() => Promise<void>) | null>;
  /** True while bulk is holding or committing — forces scheduleCommit busy path. */
  isBulkActiveRef?: React.MutableRefObject<boolean>;
}

const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);
const mergePendingKey = queryKeys.suggestions.mergePending();
const namePendingKey = queryKeys.suggestions.namePending();

const failureMessageFor = (kind: SuggestionCommitKind): string => {
  switch (kind) {
    case 'accept':
    case 'acceptMerge':
    case 'acceptName':
      return 'Accept failed. Retry or undo is unavailable after a failed save.';
    case 'reject':
    case 'rejectMerge':
    case 'rejectName':
      return 'Reject failed. Retry to try again.';
  }
};

interface HeldCommit {
  /** Monotonic identity for this hold entry (BR-22 stale-timer guard). */
  entryId: number;
  kind: SuggestionCommitKind;
  suggestionId: string;
  resolve: (result: ScheduleCommitResult) => void;
  remainingMs: number;
  deadlineMs: number;
  paused: boolean;
  timerId: ReturnType<typeof setTimeout> | null;
}

export const useSuggestionReviewMutations = ({
  queryClient,
  bulkActionRef,
  awaitBulkIdleOrFlushRef,
  isBulkActiveRef,
}: UseSuggestionReviewMutationsOptions) => {
  const mergeSurvivors = useOptionalMergeSurvivors();
  const mergeSurvivorsRef = React.useRef(mergeSurvivors);
  mergeSurvivorsRef.current = mergeSurvivors;

  const recordMergeSurvivorFromSuggestion = React.useCallback((suggestion: PendingMergeSuggestion) => {
    const api = mergeSurvivorsRef.current;
    if (!api) {
      return;
    }
    // Prefer authoritative source/target ids from accept-merge response;
    // fall back to client rank only when older backends omit them.
    const { survivorId, retiredId } = resolveMergeSurvivorFromResponse(suggestion);
    api.recordMergeSurvivor(retiredId, survivorId);
  }, []);

  /**
   * UXW2-2-R1-21: retire only the topology-checked source id from
   * authoritativeMergeSurvivor. Foreign/malformed ids → no drop (invalidation only).
   */
  const dropRetiredMergeCluster = React.useCallback(
    (response: PendingMergeSuggestion) => {
      const resolved = authoritativeMergeSurvivor(response);
      if (!resolved) {
        return;
      }
      dropClusterFromReviewCaches(queryClient, resolved.retiredId, { mode: REVIEW_DROP_MODE.MERGE });
    },
    [queryClient],
  );

  const [hold, setHold] = React.useState<CommitHoldState>({
    phase: 'idle',
    kind: null,
    suggestionId: null,
    errorMessage: null,
  });

  const [personCommit, setPersonCommit] = React.useState<PersonCommitState>({
    phase: 'idle',
    clusterId: null,
    errorMessage: null,
  });

  const mountedRef = React.useRef(true);
  const heldRef = React.useRef<HeldCommit | null>(null);
  /**
   * A-01: synchronous mirror of the VISIBLE single-item hold state. The busy path
   * awaits bulk before opening a hold, during which a DIFFERENT item's failure can
   * materialize (e.g. bulk-initiate flushes and fails a held single). The render-time
   * `hold` captured in scheduleCommit is stale by then, so async guards read this ref
   * instead. It reflects only updateUi (visible) transitions — bulk's silent
   * commitOneNow never touches it, preserving the S2-01 "gate on visible state" rule.
   */
  const holdStateRef = React.useRef<CommitHoldState>(hold);
  /** Serializes flush/schedule so at most one commit is in flight and order is preserved. */
  const chainRef = React.useRef(Promise.resolve());
  const committingRef = React.useRef(false);
  /** Person-commit POST executing (inside executePersonCommit). */
  const personCommittingRef = React.useRef(false);
  /**
   * BR-25/26: synchronous re-entry latch set at schedule/retry time (before any
   * await). Covers held-accept flush latency where phase is still 'idle'.
   */
  const personCommitInFlightRef = React.useRef(false);
  /** Last person-commit request for retry (rg-002: re-fire exactly one POST). */
  const lastPersonCommitRef = React.useRef<PersonCommitRequest | null>(null);
  /** Failed hold snapshot — used so schedule/retry can re-check without waiting on React state. */
  const failedHoldRef = React.useRef<{ kind: SuggestionCommitKind; suggestionId: string } | null>(null);
  /** BR-17: reject re-entry while a retry POST is in flight. */
  const retryInFlightRef = React.useRef(false);
  const [retryPending, setRetryPending] = React.useState(false);
  /** BR-25: disables confirm/retry immediately on schedule (not only phase==='committing'). */
  const [personCommitPending, setPersonCommitPending] = React.useState(false);
  /** BR-22: per-hold monotonically increasing entry id. */
  const nextEntryIdRef = React.useRef(1);

  const setPersonCommitSafe = React.useCallback((next: PersonCommitState) => {
    if (mountedRef.current) {
      setPersonCommit(next);
    }
  }, []);

  const removePendingSuggestionFromCache = React.useCallback(
    (suggestionId: string) => {
      queryClient.setQueryData<SuggestionReviewPage | undefined>(reviewPageKey, (current) => {
        if (!current) {
          return current;
        }
        const filtered = current.items.filter((item) => item.suggestionId !== suggestionId);
        if (filtered.length === current.items.length) {
          return current;
        }
        // COR-3 (rg-015): no envelope total to decrement; the loaded count follows items.
        return { ...current, items: filtered };
      });
    },
    [queryClient],
  );

  const removeMergeSuggestionFromCache = React.useCallback(
    (suggestionId: string) => {
      queryClient.setQueryData<PendingMergeSuggestionsResponse | undefined>(mergePendingKey, (current) => {
        if (!current) {
          return current;
        }
        const filtered = current.suggestions.filter((item) => item.id !== suggestionId);
        if (filtered.length === current.suggestions.length) {
          return current;
        }
        return { ...current, suggestions: filtered };
      });
    },
    [queryClient],
  );

  const removeNameSuggestionFromCache = React.useCallback(
    (suggestionId: string) => {
      queryClient.setQueryData<PendingNameSuggestionsResponse | undefined>(namePendingKey, (current) => {
        if (!current) {
          return current;
        }
        const filtered = current.suggestions.filter((item) => item.id !== suggestionId);
        if (filtered.length === current.suggestions.length) {
          return current;
        }
        return { ...current, suggestions: filtered };
      });
    },
    [queryClient],
  );

  const invalidateSuggestionQueries = React.useCallback(() => {
    void invalidateSuggestionProjection(queryClient);
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
  }, [queryClient]);

  const invalidateMediaIdentities = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  }, [queryClient]);

  const fireCommitApi = React.useCallback(async (kind: SuggestionCommitKind, suggestionId: string) => {
    switch (kind) {
      case 'accept':
        return acceptSuggestion(suggestionId);
      case 'reject':
        return rejectSuggestion(suggestionId);
      case 'acceptMerge':
        return acceptMergeSuggestion(suggestionId);
      case 'rejectMerge':
        return rejectMergeSuggestion(suggestionId);
      case 'acceptName':
        return acceptNameSuggestion(suggestionId);
      case 'rejectName':
        return rejectNameSuggestion(suggestionId);
    }
  }, []);

  const applySuccessSideEffects = React.useCallback(
    (kind: SuggestionCommitKind, suggestionId: string) => {
      switch (kind) {
        case 'accept':
          removePendingSuggestionFromCache(suggestionId);
          if (!bulkActionRef.current) {
            invalidateSuggestionQueries();
            invalidateMediaIdentities();
          }
          break;
        case 'reject':
          removePendingSuggestionFromCache(suggestionId);
          if (!bulkActionRef.current) {
            invalidateSuggestionQueries();
          }
          break;
        case 'acceptMerge':
          // BR-18: drop from cache before invalidation so the card leaves the queue immediately.
          removeMergeSuggestionFromCache(suggestionId);
          invalidateReviewCachesWithoutRefetch(queryClient);
          invalidateMediaIdentities();
          break;
        case 'rejectMerge':
          removeMergeSuggestionFromCache(suggestionId);
          void queryClient.invalidateQueries({ queryKey: mergePendingKey });
          break;
        case 'acceptName': {
          const names = queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey);
          const named = names?.suggestions.find((item) => item.id === suggestionId);
          if (named?.cluster_id) {
            dropClusterFromReviewCaches(queryClient, named.cluster_id, { mode: REVIEW_DROP_MODE.LABEL });
          }
          removeNameSuggestionFromCache(suggestionId);
          invalidateReviewCachesWithoutRefetch(queryClient);
          break;
        }
        case 'rejectName':
          removeNameSuggestionFromCache(suggestionId);
          void queryClient.invalidateQueries({ queryKey: namePendingKey });
          break;
      }
    },
    [
      bulkActionRef,
      invalidateMediaIdentities,
      invalidateSuggestionQueries,
      queryClient,
      removeMergeSuggestionFromCache,
      removeNameSuggestionFromCache,
      removePendingSuggestionFromCache,
    ],
  );

  const clearHeldTimer = React.useCallback(() => {
    const held = heldRef.current;
    if (held?.timerId != null) {
      clearTimeout(held.timerId);
      held.timerId = null;
    }
  }, []);

  const setHoldSafe = React.useCallback((next: CommitHoldState) => {
    // A-01: mirror synchronously so async busy-path guards see the latest visible
    // hold even before React commits the re-render.
    holdStateRef.current = next;
    if (mountedRef.current) {
      setHold(next);
    }
  }, []);

  const executeHeldCommit = React.useCallback(
    async (
      kind: SuggestionCommitKind,
      suggestionId: string,
      options: { updateUi: boolean },
    ): Promise<ScheduleCommitResult> => {
      committingRef.current = true;
      if (options.updateUi) {
        setHoldSafe({
          phase: 'committing',
          kind,
          suggestionId,
          errorMessage: null,
        });
      }

      try {
        const response = await fireCommitApi(kind, suggestionId);
        if (kind === 'acceptMerge' && response) {
          recordMergeSurvivorFromSuggestion(response as PendingMergeSuggestion);
          dropRetiredMergeCluster(response as PendingMergeSuggestion);
        }
        applySuccessSideEffects(kind, suggestionId);
        failedHoldRef.current = null;
        if (options.updateUi) {
          setHoldSafe({
            phase: 'idle',
            kind: null,
            suggestionId: null,
            errorMessage: null,
          });
        }
        return { outcome: 'committed', kind, suggestionId };
      } catch {
        failedHoldRef.current = { kind, suggestionId };
        if (options.updateUi) {
          setHoldSafe({
            phase: 'failed',
            kind,
            suggestionId,
            errorMessage: failureMessageFor(kind),
          });
        }
        return { outcome: 'failed', kind, suggestionId };
      } finally {
        committingRef.current = false;
      }
    },
    [applySuccessSideEffects, dropRetiredMergeCluster, fireCommitApi, recordMergeSurvivorFromSuggestion, setHoldSafe],
  );

  const flushHeldInternal = React.useCallback(
    async (options: { updateUi: boolean }): Promise<ScheduleCommitResult | null> => {
      const held = heldRef.current;
      if (!held) {
        return null;
      }
      clearHeldTimer();
      heldRef.current = null;
      const result = await executeHeldCommit(held.kind, held.suggestionId, options);
      held.resolve(result);
      return result;
    },
    [clearHeldTimer, executeHeldCommit],
  );

  const armHoldTimer = React.useCallback(() => {
    const held = heldRef.current;
    if (!held || held.paused) {
      return;
    }
    clearHeldTimer();
    held.deadlineMs = Date.now() + held.remainingMs;
    const entryId = held.entryId;
    held.timerId = setTimeout(() => {
      // Fire on window close — chained so it never races a concurrent schedule.
      const fire = async () => {
        // BR-22: match entry identity, not just kind+id (undo→re-accept must not truncate).
        if (heldRef.current?.entryId !== entryId) {
          return;
        }
        await flushHeldInternal({ updateUi: true });
      };
      const scheduled = chainRef.current.then(fire, fire);
      chainRef.current = scheduled.then(
        () => undefined,
        () => undefined,
      );
      void scheduled;
    }, held.remainingMs);
  }, [clearHeldTimer, flushHeldInternal]);

  const openHold = React.useCallback(
    (kind: SuggestionCommitKind, suggestionId: string): Promise<ScheduleCommitResult> =>
      new Promise<ScheduleCommitResult>((resolve) => {
        // BR-23: never arm UI/timer after unmount.
        if (!mountedRef.current) {
          resolve({ outcome: 'failed', kind, suggestionId });
          return;
        }
        // Clear a prior failure surface when a new action starts.
        failedHoldRef.current = null;
        const entry: HeldCommit = {
          entryId: nextEntryIdRef.current++,
          kind,
          suggestionId,
          resolve,
          remainingMs: UNDO_HOLD_MS,
          deadlineMs: Date.now() + UNDO_HOLD_MS,
          paused: false,
          timerId: null,
        };
        heldRef.current = entry;
        setHoldSafe({
          phase: 'holding',
          kind,
          suggestionId,
          errorMessage: null,
        });
        armHoldTimer();
      }),
    [armHoldTimer, setHoldSafe],
  );

  const scheduleCommit = React.useCallback(
    (kind: SuggestionCommitKind, suggestionId: string): Promise<ScheduleCommitResult> => {
      // BR-17: failed same item blocks new schedules — retry is the only path.
      if (hold.phase === 'failed' && hold.suggestionId === suggestionId) {
        return Promise.resolve({ outcome: 'failed', kind, suggestionId });
      }

      // S2-01 [CON-05]: the single-item hold/failure slot is a single slot. A DIFFERENT
      // item's unresolved failure must NOT be silently cleared by openHold — that erases
      // the error surface and abandons an un-committed item the user believes was saved.
      // Refuse the new action (resolve with ITS own identity) until the failed item is
      // retried to success. Key off the VISIBLE hold state, not failedHoldRef: bulk's
      // commitOneNow sets failedHoldRef with updateUi:false (bulk owns its own partial-
      // failure surface + Retry), so gating on failedHoldRef would wrongly block singles
      // after a bulk partial failure with no single-item Retry path (grok GFR review).
      if (hold.phase === 'failed' && hold.suggestionId && hold.suggestionId !== suggestionId) {
        return Promise.resolve({ outcome: 'not_attempted_prior_failed', kind, suggestionId });
      }

      // Idle path: open the hold synchronously so the Saving… state is visible in the
      // same turn as the click (tests and AT both observe this immediately).
      // When bulk is holding/committing, take the busy path so bulk flushes first (PR-30).
      if (
        !heldRef.current &&
        !committingRef.current &&
        !personCommittingRef.current &&
        !isBulkActiveRef?.current
      ) {
        return openHold(kind, suggestionId);
      }

      // BR-49: await bulk OUTSIDE chainRef. Bulk's runSequence → commitOneNow must not
      // enqueue behind a chain link that is itself waiting for bulk (circular wait).
      const runBusy = async (): Promise<ScheduleCommitResult> => {
        if (!mountedRef.current) {
          return { outcome: 'failed', kind, suggestionId };
        }
        const awaitBulk = awaitBulkIdleOrFlushRef?.current;
        if (awaitBulk) {
          await awaitBulk();
        }
        if (!mountedRef.current) {
          return { outcome: 'failed', kind, suggestionId };
        }

        // Busy path: chain only the prepare step (flush prior + open hold). The returned
        // promise tracks the full hold lifetime; chainRef must NOT await that lifetime or
        // flushHeld / next schedule deadlock waiting for a window that needs them to fire.
        return new Promise<ScheduleCommitResult>((resolve) => {
          const prepare = async (): Promise<void> => {
            // BR-23: drop late prepares after unmount.
            if (!mountedRef.current) {
              resolve({ outcome: 'failed', kind, suggestionId });
              return;
            }
            if (heldRef.current) {
              const prior = await flushHeldInternal({ updateUi: true });
              // Failed prior stays at queue head with alert — do not open a second window.
              if (prior?.outcome === 'failed') {
                // BR-21: resolve with THIS action's kind/id, not the prior item's result.
                resolve({
                  outcome: 'not_attempted_prior_failed',
                  kind,
                  suggestionId,
                });
                return;
              }
            }
            while (committingRef.current || personCommittingRef.current) {
              await Promise.resolve();
            }
            if (!mountedRef.current) {
              resolve({ outcome: 'failed', kind, suggestionId });
              return;
            }
            // BR-17: same item still failed after chain — do not open a second path.
            if (failedHoldRef.current?.suggestionId === suggestionId) {
              resolve({ outcome: 'failed', kind, suggestionId });
              return;
            }
            // S2-01 (A-01): a DIFFERENT item's VISIBLE failure may have materialized
            // during awaitBulk (e.g. bulk-initiate flushed and failed the held single
            // A while this B was parked). openHold would null failedHoldRef + overwrite
            // the hold, silently erasing A's failure surface. Re-check the LIVE hold
            // (not the stale entry-time closure) and refuse instead of opening.
            const liveHold = holdStateRef.current;
            if (
              liveHold.phase === 'failed' &&
              liveHold.suggestionId &&
              liveHold.suggestionId !== suggestionId
            ) {
              resolve({ outcome: 'not_attempted_prior_failed', kind, suggestionId });
              return;
            }
            void openHold(kind, suggestionId).then(resolve);
          };

          chainRef.current = chainRef.current.then(prepare, prepare).then(
            () => undefined,
            () => undefined,
          );
        });
      };

      return runBusy();
    },
    [
      awaitBulkIdleOrFlushRef,
      flushHeldInternal,
      hold.phase,
      hold.suggestionId,
      isBulkActiveRef,
      openHold,
    ],
  );

  const undoHold = React.useCallback((): void => {
    const held = heldRef.current;
    if (!held) {
      return;
    }
    clearHeldTimer();
    heldRef.current = null;
    held.resolve({ outcome: 'undone', kind: held.kind, suggestionId: held.suggestionId });
    setHoldSafe({
      phase: 'idle',
      kind: null,
      suggestionId: null,
      errorMessage: null,
    });
  }, [clearHeldTimer, setHoldSafe]);

  const retryFailure = React.useCallback((): Promise<ScheduleCommitResult> | null => {
    if (hold.phase !== 'failed' || !hold.kind || !hold.suggestionId) {
      return null;
    }
    // BR-17: synchronous re-entry guard before any async work.
    if (retryInFlightRef.current || committingRef.current) {
      return null;
    }
    retryInFlightRef.current = true;
    if (mountedRef.current) {
      setRetryPending(true);
    }
    const kind = hold.kind;
    const suggestionId = hold.suggestionId;
    const run = async (): Promise<ScheduleCommitResult> => {
      // Re-check the failed hold is still current for this kind+id.
      if (
        failedHoldRef.current?.kind !== kind ||
        failedHoldRef.current?.suggestionId !== suggestionId
      ) {
        return { outcome: 'failed', kind, suggestionId };
      }
      // Retry re-fires exactly one POST for the failed item (no new undo window).
      return executeHeldCommit(kind, suggestionId, { updateUi: true });
    };
    const scheduled = chainRef.current.then(run, run).finally(() => {
      retryInFlightRef.current = false;
      if (mountedRef.current) {
        setRetryPending(false);
      }
    });
    chainRef.current = scheduled.then(
      () => undefined,
      () => undefined,
    );
    return scheduled;
  }, [executeHeldCommit, hold.kind, hold.phase, hold.suggestionId]);

  const setHoldPaused = React.useCallback(
    (paused: boolean): void => {
      // heldRef is only set while phase === 'holding' (cleared on flush/undo).
      const held = heldRef.current;
      if (!held) {
        return;
      }
      if (paused === held.paused) {
        return;
      }
      if (paused) {
        // Pause countdown while focus/hover is on the hold region (A11Y-16).
        if (held.timerId != null) {
          held.remainingMs = Math.max(0, held.deadlineMs - Date.now());
          clearHeldTimer();
        }
        held.paused = true;
      } else {
        held.paused = false;
        armHoldTimer();
      }
    },
    [armHoldTimer, clearHeldTimer],
  );

  /** Flush the held commit now (next action / navigation). Awaits the POST. */
  const flushHeld = React.useCallback((): Promise<ScheduleCommitResult | null> => {
    const run = async () => flushHeldInternal({ updateUi: true });
    const scheduled = chainRef.current.then(run, run);
    chainRef.current = scheduled.then(
      () => undefined,
      () => undefined,
    );
    return scheduled;
  }, [flushHeldInternal]);

  /**
   * Slice-5 bulk: fire one atomic commit without hold UI (side-effects on success).
   * Caller owns single-in-flight sequencing across the bulk set.
   * BR-49: executes directly — does NOT enqueue on chainRef (bulk already serializes;
   * re-entering chain from awaitBulkIdleOrFlush would deadlock with pre-chain waiters).
   */
  const commitOneNow = React.useCallback(
    async (
      kind: SuggestionCommitKind,
      suggestionId: string,
    ): Promise<'committed' | 'failed'> => {
      const result = await executeHeldCommit(kind, suggestionId, { updateUi: false });
      return result.outcome === 'committed' ? 'committed' : 'failed';
    },
    [executeHeldCommit],
  );

  /** True while a single-item hold/commit targets this suggestion id (select exclusion). */
  const isSuggestionHeld = React.useCallback(
    (suggestionId: string): boolean => {
      if (!hold.suggestionId || hold.suggestionId !== suggestionId) {
        return false;
      }
      return hold.phase === 'holding' || hold.phase === 'committing' || hold.phase === 'failed';
    },
    [hold.phase, hold.suggestionId],
  );

  /**
   * Slice 3: person-commit fires immediately (no undo hold) after flushing any
   * held accept/reject. Shares chainRef so commits never overlap (rg-002 / §3).
   */
  const executePersonCommit = React.useCallback(
    async (request: PersonCommitRequest): Promise<PersonCommitResult> => {
      personCommittingRef.current = true;
      lastPersonCommitRef.current = request;
      setPersonCommitSafe({
        phase: 'committing',
        clusterId: request.clusterId,
        errorMessage: null,
      });

      try {
        await commitClusterToRosterEntry({
          clusterId: request.clusterId,
          rosterEntryId: request.rosterEntryId,
          newEntryName: request.newEntryName,
        });
        // BR-28: clusterLabelSetClear kept targets (extras allowed).
        // S2-02 [CON-05] / R1-16: mark review feeds stale WITHOUT an immediate refetch.
        // Backend curation lags the write; refetch-now restores the dropped row.
        invalidateReviewCachesWithoutRefetch(queryClient);
        void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.labels(), refetchType: 'none' });
        void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities(), refetchType: 'none' });
        void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
        dropClusterFromReviewCaches(queryClient, request.clusterId, { mode: REVIEW_DROP_MODE.LABEL });
        setPersonCommitSafe({
          phase: 'succeeded',
          clusterId: request.clusterId,
          errorMessage: null,
        });
        return { outcome: 'committed', clusterId: request.clusterId };
      } catch {
        setPersonCommitSafe({
          phase: 'failed',
          clusterId: request.clusterId,
          errorMessage: PERSON_COMMIT_FAILURE_COPY,
        });
        return { outcome: 'failed', clusterId: request.clusterId };
      } finally {
        personCommittingRef.current = false;
      }
    },
    [queryClient, setPersonCommitSafe],
  );

  const schedulePersonCommit = React.useCallback(
    (request: PersonCommitRequest): Promise<PersonCommitResult> => {
      // S2-01 [CON-05]: a person-commit must not proceed while a single-item accept/reject
      // failure is unresolved. Its success invalidates the projection and can drop the
      // failed card from cache — stranding the failed slot with no reachable Retry. Refuse
      // until the failure is retried to success (same single-slot honesty as scheduleCommit).
      if (hold.phase === 'failed' && hold.suggestionId) {
        return Promise.resolve({ outcome: 'not_attempted_prior_failed', clusterId: request.clusterId });
      }
      // BR-25: synchronous re-entry gate before any async work / flush latency.
      if (personCommitInFlightRef.current) {
        return Promise.resolve({ outcome: 'failed', clusterId: request.clusterId });
      }
      personCommitInFlightRef.current = true;
      if (mountedRef.current) {
        setPersonCommitPending(true);
      }

      // BR-48/49: await bulk OUTSIDE chainRef (same restructure as scheduleCommit).
      const run = async (): Promise<PersonCommitResult> => {
        try {
          if (!mountedRef.current) {
            return { outcome: 'failed', clusterId: request.clusterId };
          }
          const awaitBulk = awaitBulkIdleOrFlushRef?.current;
          if (awaitBulk) {
            await awaitBulk();
          }
          if (!mountedRef.current) {
            return { outcome: 'failed', clusterId: request.clusterId };
          }

          return await new Promise<PersonCommitResult>((resolve) => {
            const prepare = async (): Promise<void> => {
              try {
                if (!mountedRef.current) {
                  resolve({ outcome: 'failed', clusterId: request.clusterId });
                  return;
                }
                // Flush any held accept/reject first (single-in-flight).
                if (heldRef.current) {
                  const prior = await flushHeldInternal({ updateUi: true });
                  if (prior?.outcome === 'failed') {
                    resolve({
                      outcome: 'not_attempted_prior_failed',
                      clusterId: request.clusterId,
                    });
                    return;
                  }
                }
                while (committingRef.current || personCommittingRef.current) {
                  await Promise.resolve();
                }
                if (!mountedRef.current) {
                  resolve({ outcome: 'failed', clusterId: request.clusterId });
                  return;
                }
                // S2-01 (A-01): an accept/reject failure that materialized during the
                // awaited window must block the person-commit (its success invalidates
                // the projection and can drop the failed card). Re-check LIVE hold, not
                // the stale entry-time closure.
                const liveHold = holdStateRef.current;
                if (liveHold.phase === 'failed' && liveHold.suggestionId) {
                  resolve({ outcome: 'not_attempted_prior_failed', clusterId: request.clusterId });
                  return;
                }
                const result = await executePersonCommit(request);
                resolve(result);
              } catch {
                resolve({ outcome: 'failed', clusterId: request.clusterId });
              }
            };

            chainRef.current = chainRef.current.then(prepare, prepare).then(
              () => undefined,
              () => undefined,
            );
          });
        } finally {
          personCommitInFlightRef.current = false;
          if (mountedRef.current) {
            setPersonCommitPending(false);
          }
        }
      };

      return run();
    },
    [awaitBulkIdleOrFlushRef, executePersonCommit, flushHeldInternal, hold.phase, hold.suggestionId],
  );

  const retryPersonCommit = React.useCallback((): Promise<PersonCommitResult> | null => {
    const last = lastPersonCommitRef.current;
    // BR-26: phase + sync latch — reject double-retry before any async work.
    if (!last || personCommit.phase !== 'failed') {
      return null;
    }
    if (
      personCommitInFlightRef.current ||
      personCommittingRef.current ||
      committingRef.current
    ) {
      return null;
    }
    return schedulePersonCommit(last);
  }, [personCommit.phase, schedulePersonCommit]);

  const clearPersonCommitSuccess = React.useCallback((): void => {
    if (personCommit.phase === 'succeeded' || personCommit.phase === 'failed') {
      setPersonCommitSafe({ phase: 'idle', clusterId: null, errorMessage: null });
    }
  }, [personCommit.phase, setPersonCommitSafe]);

  // Unmount: fire any held commit without awaiting in cleanup; never setState after unmount.
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const held = heldRef.current;
      if (!held) {
        return;
      }
      clearHeldTimer();
      heldRef.current = null;
      // Do not resolve as committed before the POST — callers unmounted; hang is fine.
      // Fire-and-forget — no UI update path (RLSE-05: no await-in-cleanup).
      void fireCommitApi(held.kind, held.suggestionId).then(
        (response) => {
          if (held.kind === 'acceptMerge' && response) {
            recordMergeSurvivorFromSuggestion(response as PendingMergeSuggestion);
            dropRetiredMergeCluster(response as PendingMergeSuggestion);
          }
          applySuccessSideEffects(held.kind, held.suggestionId);
        },
        () => {
          // Rejection leaves the item un-accepted — honest re-appear on next mount.
        },
      );
    };
  }, [applySuccessSideEffects, clearHeldTimer, dropRetiredMergeCluster, fireCommitApi, recordMergeSurvivorFromSuggestion]);

  // Raw mutations remain for bulkAccept and any direct callers; assignment accept/reject
  // no longer use optimistic onMutate — ReviewQueue schedules through the hold API.
  const acceptMutation = useMutation({
    mutationFn: acceptSuggestion,
    onSuccess: (_data, suggestionId) => {
      removePendingSuggestionFromCache(suggestionId);
    },
    onSettled: () => {
      if (!bulkActionRef.current) {
        invalidateSuggestionQueries();
        invalidateMediaIdentities();
      }
    },
  });

  const rejectMutation = useMutation({
    mutationFn: rejectSuggestion,
    onSuccess: (_data, suggestionId) => {
      removePendingSuggestionFromCache(suggestionId);
    },
    onSettled: () => {
      if (!bulkActionRef.current) {
        invalidateSuggestionQueries();
      }
    },
  });

  const acceptMergeMutation = useMutation({
    mutationFn: acceptMergeSuggestion,
    onSuccess: (data, suggestionId) => {
      recordMergeSurvivorFromSuggestion(data);
      dropRetiredMergeCluster(data);
      removeMergeSuggestionFromCache(suggestionId);
      invalidateReviewCachesWithoutRefetch(queryClient);
      invalidateMediaIdentities();
    },
  });

  const rejectMergeMutation = useMutation({
    mutationFn: rejectMergeSuggestion,
    onSuccess: (_data, suggestionId) => {
      removeMergeSuggestionFromCache(suggestionId);
      void queryClient.invalidateQueries({ queryKey: mergePendingKey });
    },
  });

  const acceptNameMutation = useMutation({
    mutationFn: acceptNameSuggestion,
    onSuccess: (_data, suggestionId) => {
      const names = queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey);
      const named = names?.suggestions.find((item) => item.id === suggestionId);
      if (named?.cluster_id) {
        dropClusterFromReviewCaches(queryClient, named.cluster_id, { mode: REVIEW_DROP_MODE.LABEL });
      }
      removeNameSuggestionFromCache(suggestionId);
      invalidateReviewCachesWithoutRefetch(queryClient);
    },
  });

  const rejectNameMutation = useMutation({
    mutationFn: rejectNameSuggestion,
    onSuccess: (_data, suggestionId) => {
      removeNameSuggestionFromCache(suggestionId);
      void queryClient.invalidateQueries({ queryKey: namePendingKey });
    },
  });

  const bulkAcceptMutation = useMutation({
    mutationFn: async (request: Parameters<typeof bulkAcceptSuggestions>[0]) => {
      // BulkAcceptResponse is {accepted_count, skipped_count} only — no accepted
      // ids. Assignment/merge drops would guess from min_confidence (rg-015).
      if (request.suggestion_type !== 'name') {
        throw new Error('Bulk accept is only available for name suggestions.');
      }
      return bulkAcceptSuggestions(request);
    },
    onSuccess: (_data, request) => {
      const names = queryClient.getQueryData<PendingNameSuggestionsResponse>(namePendingKey);
      for (const item of names?.suggestions ?? []) {
        if ((item.confidence_score ?? 0) >= request.min_confidence) {
          dropClusterFromReviewCaches(queryClient, item.cluster_id, { mode: REVIEW_DROP_MODE.LABEL });
        }
      }
      invalidateReviewCachesWithoutRefetch(queryClient);
    },
  });

  const isHoldActive = hold.phase === 'holding' || hold.phase === 'committing';
  const isCommitting =
    hold.phase === 'committing' ||
    personCommit.phase === 'committing' ||
    personCommitPending;

  /**
   * BR-15: only the held/failed card's accept/reject are disabled during a hold.
   * Other cards stay enabled so scheduleCommit's busy path can flush → open.
   * During 'committing' the committing card stays briefly disabled.
   * Person-commit in flight also disables accept/reject (shared chain).
   */
  const isCardActionsDisabled = React.useCallback(
    (suggestionId: string, kinds: readonly SuggestionCommitKind[]): boolean => {
      if (
        acceptMutation.isPending ||
        rejectMutation.isPending ||
        acceptMergeMutation.isPending ||
        rejectMergeMutation.isPending ||
        acceptNameMutation.isPending ||
        rejectNameMutation.isPending ||
        personCommit.phase === 'committing' ||
        personCommitPending
      ) {
        return true;
      }
      if (hold.phase === 'idle' || !hold.suggestionId || hold.kind === null) {
        return false;
      }
      if (hold.suggestionId !== suggestionId) {
        return false;
      }
      if (hold.phase === 'failed') {
        return true;
      }
      if (hold.phase === 'holding' || hold.phase === 'committing') {
        return kinds.includes(hold.kind);
      }
      return false;
    },
    [
      acceptMergeMutation.isPending,
      acceptMutation.isPending,
      acceptNameMutation.isPending,
      hold.kind,
      hold.phase,
      hold.suggestionId,
      personCommit.phase,
      personCommitPending,
      rejectMergeMutation.isPending,
      rejectMutation.isPending,
      rejectNameMutation.isPending,
    ],
  );

  return {
    hold,
    holdAnnounce: HOLD_STATUS_COPY,
    isHoldActive,
    isCommitting,
    isCardActionsDisabled,
    retryPending,
    personCommit,
    personCommitPending,
    scheduleAccept: (suggestionId: string) => scheduleCommit('accept', suggestionId),
    scheduleReject: (suggestionId: string) => scheduleCommit('reject', suggestionId),
    scheduleAcceptMerge: (suggestionId: string) => scheduleCommit('acceptMerge', suggestionId),
    scheduleRejectMerge: (suggestionId: string) => scheduleCommit('rejectMerge', suggestionId),
    scheduleAcceptName: (suggestionId: string) => scheduleCommit('acceptName', suggestionId),
    scheduleRejectName: (suggestionId: string) => scheduleCommit('rejectName', suggestionId),
    schedulePersonCommit,
    retryPersonCommit,
    clearPersonCommitSuccess,
    undoHold,
    retryFailure,
    setHoldPaused,
    flushHeld,
    commitOneNow,
    isSuggestionHeld,
    mutations: {
      accept: acceptMutation,
      reject: rejectMutation,
      acceptMerge: acceptMergeMutation,
      rejectMerge: rejectMergeMutation,
      acceptName: acceptNameMutation,
      rejectName: rejectNameMutation,
      bulkAccept: bulkAcceptMutation,
    },
    invalidateSuggestionQueries,
    invalidateMediaIdentities,
  };
};

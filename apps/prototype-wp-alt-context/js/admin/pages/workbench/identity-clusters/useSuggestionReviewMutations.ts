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
import { invalidateSuggestionProjection } from './suggestionProjection';
import type { SuggestionReviewPage } from './useSuggestionReviewQueries';

/** Pinned undo hold window — unit, e2e, and AT scripts share this single constant. */
export const UNDO_HOLD_MS = 5000;

/** Single hold/status copy — component + tests consume this export (BR-24). */
export const HOLD_STATUS_COPY = 'Saving… — Undo';

export type SuggestionCommitKind =
  | 'accept'
  | 'reject'
  | 'acceptMerge'
  | 'rejectMerge'
  | 'acceptName'
  | 'rejectName';

export type CommitHoldPhase = 'idle' | 'holding' | 'committing' | 'failed';

export interface CommitHoldState {
  phase: CommitHoldPhase;
  kind: SuggestionCommitKind | null;
  suggestionId: string | null;
  /** User-facing failure copy when phase === 'failed'. */
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

interface UseSuggestionReviewMutationsOptions {
  queryClient: QueryClient;
  bulkActionRef: React.MutableRefObject<boolean>;
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
}: UseSuggestionReviewMutationsOptions) => {
  const [hold, setHold] = React.useState<CommitHoldState>({
    phase: 'idle',
    kind: null,
    suggestionId: null,
    errorMessage: null,
  });

  const mountedRef = React.useRef(true);
  const heldRef = React.useRef<HeldCommit | null>(null);
  /** Serializes flush/schedule so at most one commit is in flight and order is preserved. */
  const chainRef = React.useRef(Promise.resolve());
  const committingRef = React.useRef(false);
  /** Failed hold snapshot — used so schedule/retry can re-check without waiting on React state. */
  const failedHoldRef = React.useRef<{ kind: SuggestionCommitKind; suggestionId: string } | null>(null);
  /** BR-17: reject re-entry while a retry POST is in flight. */
  const retryInFlightRef = React.useRef(false);
  const [retryPending, setRetryPending] = React.useState(false);
  /** BR-22: per-hold monotonically increasing entry id. */
  const nextEntryIdRef = React.useRef(1);

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
          void queryClient.invalidateQueries({ queryKey: mergePendingKey });
          invalidateMediaIdentities();
          void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
          break;
        case 'rejectMerge':
          removeMergeSuggestionFromCache(suggestionId);
          void queryClient.invalidateQueries({ queryKey: mergePendingKey });
          break;
        case 'acceptName':
          removeNameSuggestionFromCache(suggestionId);
          void queryClient.invalidateQueries({ queryKey: namePendingKey });
          break;
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
        await fireCommitApi(kind, suggestionId);
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
    [applySuccessSideEffects, fireCommitApi, setHoldSafe],
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

      // Idle path: open the hold synchronously so the Saving… state is visible in the
      // same turn as the click (tests and AT both observe this immediately).
      if (!heldRef.current && !committingRef.current) {
        return openHold(kind, suggestionId);
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
          while (committingRef.current) {
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
          void openHold(kind, suggestionId).then(resolve);
        };

        chainRef.current = chainRef.current.then(prepare, prepare).then(
          () => undefined,
          () => undefined,
        );
      });
    },
    [flushHeldInternal, hold.phase, hold.suggestionId, openHold],
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
        () => {
          applySuccessSideEffects(held.kind, held.suggestionId);
        },
        () => {
          // Rejection leaves the item un-accepted — honest re-appear on next mount.
        },
      );
    };
  }, [applySuccessSideEffects, clearHeldTimer, fireCommitApi]);

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
    onSuccess: (_data, suggestionId) => {
      removeMergeSuggestionFromCache(suggestionId);
      void queryClient.invalidateQueries({ queryKey: mergePendingKey });
      invalidateMediaIdentities();
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
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
      removeNameSuggestionFromCache(suggestionId);
      void queryClient.invalidateQueries({ queryKey: namePendingKey });
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
    mutationFn: bulkAcceptSuggestions,
    onSuccess: () => {
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: namePendingKey });
      void queryClient.invalidateQueries({ queryKey: mergePendingKey });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
  });

  const isHoldActive = hold.phase === 'holding' || hold.phase === 'committing';
  const isCommitting = hold.phase === 'committing';

  /**
   * BR-15: only the held/failed card's accept/reject are disabled during a hold.
   * Other cards stay enabled so scheduleCommit's busy path can flush → open.
   * During 'committing' the committing card stays briefly disabled.
   */
  const isCardActionsDisabled = React.useCallback(
    (suggestionId: string, kinds: readonly SuggestionCommitKind[]): boolean => {
      if (
        acceptMutation.isPending ||
        rejectMutation.isPending ||
        acceptMergeMutation.isPending ||
        rejectMergeMutation.isPending ||
        acceptNameMutation.isPending ||
        rejectNameMutation.isPending
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
    scheduleAccept: (suggestionId: string) => scheduleCommit('accept', suggestionId),
    scheduleReject: (suggestionId: string) => scheduleCommit('reject', suggestionId),
    scheduleAcceptMerge: (suggestionId: string) => scheduleCommit('acceptMerge', suggestionId),
    scheduleRejectMerge: (suggestionId: string) => scheduleCommit('rejectMerge', suggestionId),
    scheduleAcceptName: (suggestionId: string) => scheduleCommit('acceptName', suggestionId),
    scheduleRejectName: (suggestionId: string) => scheduleCommit('rejectName', suggestionId),
    undoHold,
    retryFailure,
    setHoldPaused,
    flushHeld,
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

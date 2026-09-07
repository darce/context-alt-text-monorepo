/**
 * Drives one bounded live describe run for the guided prototype.
 *
 * The reducer in `liveDescription.ts` owns every state transition; this hook
 * owns only the I/O and the clock. Keeping the split that way means the wait
 * bounds are testable without a network and the network is testable without
 * re-deriving the state machine.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from 'react';

import {
  cancelBulkDescribeRun,
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  fetchBulkDescribeRun,
  fetchDescribeRunItems,
  isDescribeRunTerminal,
  isGpuState,
  submitBulkDescribeRun,
} from '../api/describeApi';
import type { DescribeRunItemsResponse, DescribeRunResponse } from '../api/describeApi';
import { isFrozenPollFailure } from '../hooks/useDescribeRunProgress';
import { createLogger } from '../utils/logger';
import {
  GUIDED_LIVE_STATUS,
  GUIDED_LIVE_WARM_CEILING_SECONDS,
  guidedLiveCeilingSecondsFor,
  guidedLiveNamingDisclosure,
  guidedLivePollDelayMs,
  guidedLiveRequestPayload,
  GUIDED_LIVE_BLOCKED_REASON,
  GUIDED_LIVE_REASON,
  guidedLiveReducer,
  guidedLiveOwnsRunAttempt,
  guidedLiveRunMayBeLive,
  initialGuidedLiveState,
  isGuidedLiveWaiting,
} from './liveDescription';
import type {
  GuidedLiveBlockedReason,
  GuidedLiveGpuState,
  GuidedLiveNamingDisclosure,
  GuidedLivePhase,
  GuidedLiveState,
  GuidedLiveTier,
} from './liveDescription';
import { GUIDED_IDENTITY_STATUS } from './state';
import type { GuidedScenario } from './state';

// The warm/cold ceilings and the warm-up leg they are built from live beside
// the reducer that enforces them; re-exported here because this hook is where
// every consumer already imports the ceiling from.
export { GUIDED_LIVE_WARM_CEILING_SECONDS };

const TICK_MS = 1000;

const liveLog = createLogger('guided.live');

/**
 * Hand a run back to the server and say so when that fails.
 *
 * Cancellation here is a REQUEST -- the route records cancel_requested and a
 * worker observes it later -- so the only thing the browser can know is whether
 * the request was accepted. Swallowing the rejection made the two states
 * indistinguishable: an expired nonce answering 403 looked exactly like a
 * clean stop, while the run kept the single GPU. Logging is the whole fix; the
 * screen deliberately stops either way, because a learner who pressed Stop
 * should not be left watching a spinner nobody owns.
 */
const releaseRun = (
  client: GuidedLiveDescriptionClient,
  runId: string,
  because: string,
): Promise<void> =>
  client
    .cancel(runId)
    .then(() => undefined)
    .catch((error: unknown) => {
      liveLog.warn('describe run cancel was not accepted; the run may still hold the GPU', {
        runId,
        because,
        error,
      });
    });

export interface GuidedLiveDescriptionClient {
  // Both the submit response and every status poll carry `deadline_seconds` on
  // the shared contract, so both are typed by it rather than by a local
  // intersection that a schema rename could not break (rg-015).
  submit: (mediaId: number) => Promise<DescribeRunResponse>;
  poll: (runId: string) => Promise<DescribeRunResponse>;
  items: (runId: string) => Promise<DescribeRunItemsResponse>;
  cancel: (runId: string) => Promise<unknown>;
}

const defaultClient: GuidedLiveDescriptionClient = {
  // The payload builder is the single place that decides what leaves the
  // browser, so the route never sees anything the guided screen invented.
  submit: (mediaId) => submitBulkDescribeRun(guidedLiveRequestPayload(mediaId).media_ids),
  poll: fetchBulkDescribeRun,
  items: fetchDescribeRunItems,
  cancel: cancelBulkDescribeRun,
};

export type { GuidedLiveBlockedReason };

export interface UseGuidedLiveDescriptionOptions {
  scenario: GuidedScenario;
  /** The real attachment the live run describes; null when the demo has none configured. */
  mediaId: number | null;
  client?: GuidedLiveDescriptionClient;
}

export interface UseGuidedLiveDescriptionResult {
  state: GuidedLiveState;
  disclosure: GuidedLiveNamingDisclosure;
  blockedReason: GuidedLiveBlockedReason | null;
  canRequest: boolean;
  canCancel: boolean;
  /**
   * True exactly when the client stopped waiting on a run the server may still
   * be finishing. The only state in which "keep waiting" is a real offer
   * rather than a second burst (INT-08).
   */
  canKeepWaiting: boolean;
  request: () => void;
  cancel: () => void;
  keepWaiting: () => void;
}

const gpuStateOf = (value: unknown): GuidedLiveGpuState => (isGpuState(value) ? value : 'unknown');

/**
 * The run's own terminal statuses outrank `phase`. A run can settle
 * (`completed_with_errors`, `failed`, `cancelled`) while `phase` still reads as
 * a running sub-phase; without this the guided screen would poll a finished run
 * all the way to its client deadline and report a timeout that never happened.
 * `isDescribeRunTerminal` is the one shared owner of that question -- guessing
 * it locally is how the two surfaces drift.
 */
const terminalPhaseFor = (status: DescribeRunResponse['status']): GuidedLivePhase => {
  switch (status) {
    case DESCRIBE_RUN_STATUS.FAILED:
      return DESCRIBE_RUN_PHASE.FAILED;
    case DESCRIBE_RUN_STATUS.CANCELLED:
      return DESCRIBE_RUN_PHASE.CANCELLED;
    default:
      return DESCRIBE_RUN_PHASE.COMPLETE;
  }
};

/**
 * Null means the service named a phase this client does not know. `phase` is
 * external JSON, so that is reachable; treating it as queued polled a finished
 * run to its deadline and reported a timeout that never happened. Boundary data
 * gets an explicit answer rather than a lenient default (sr-005).
 */
const phaseOf = (run: DescribeRunResponse): GuidedLivePhase | null => {
  switch (run.phase) {
    case DESCRIBE_RUN_PHASE.COMPLETE:
    case DESCRIBE_RUN_PHASE.FAILED:
    case DESCRIBE_RUN_PHASE.CANCELLED:
      return run.phase;
    case DESCRIBE_RUN_PHASE.WARMING:
    case DESCRIBE_RUN_PHASE.DESCRIBING:
    case DESCRIBE_RUN_PHASE.QUEUED:
      return isDescribeRunTerminal(run.status) ? terminalPhaseFor(run.status) : run.phase;
    default:
      return null;
  }
};

/**
 * Null means "this run produced nothing for the image on screen". Falling back
 * to `items[0]` would show a confident sentence about a different photograph,
 * which is worse than showing nothing at all.
 */
const draftOf = (
  items: DescribeRunItemsResponse,
  mediaId: number,
): { text: string | null; tier: GuidedLiveTier | null } | null => {
  const item = items.items.find((row) => row.media_id === mediaId);
  if (item === undefined) {
    return null;
  }
  return { text: item.alt_text_draft ?? null, tier: item.tier ?? null };
};

export const useGuidedLiveDescription = ({
  scenario,
  mediaId,
  client = defaultClient,
}: UseGuidedLiveDescriptionOptions): UseGuidedLiveDescriptionResult => {


  // A run generation fences every in-flight promise: a poll resolving after a
  // cancel or a new request must not write into the run that replaced it.
  const generationRef = useRef(0);
  const attemptRef = useRef(0);

  // "Decided" means every face has an answer -- confirmed OR marked
  // unidentified. Counting only confirmations let a learner who marked every
  // face unidentified stay blocked forever, and let a learner who answered one
  // of two faces start a run while the other was still open.
  const facesDecided = scenario.identities.every(
    (identity) => identity.status !== GUIDED_IDENTITY_STATUS.UNCONFIRMED,
  );
  const blockedReason: GuidedLiveBlockedReason | null = !facesDecided
    ? GUIDED_LIVE_BLOCKED_REASON.NO_FACES_DECIDED
    : mediaId === null
      ? GUIDED_LIVE_BLOCKED_REASON.NO_MEDIA
      : null;

  // Seeded from the same prop the effect below reconciles it to, so the very
  // first commit already agrees with itself. Starting unconditionally blocked
  // meant a fully-decided scenario painted a disabled button beside the idle
  // sentence until a passive effect caught up.
  const [state, dispatch] = useReducer(guidedLiveReducer, blockedReason, initialGuidedLiveState);

  const waiting = isGuidedLiveWaiting(state.status);
  const runId = state.runId;

  // Re-opening a face while a run is in flight invalidates that run. The
  // reducer stops the screen; the burst it started keeps costing money until
  // the server hears about it, so fence the generation and cancel the run id.
  const mayBeLive = guidedLiveRunMayBeLive(state);
  const ownsAttempt = guidedLiveOwnsRunAttempt(state);
  const waitingRef = useRef<{ mayBeLive: boolean; ownsAttempt: boolean; runId: string | null }>({
    mayBeLive,
    ownsAttempt,
    runId,
  });
  waitingRef.current = { mayBeLive, ownsAttempt, runId };

  // Layout, not passive: the gate closing is a fact about this render, and a
  // passive effect would let the browser paint one frame of the old run's
  // glyph and sentence underneath the new blocked copy.
  useLayoutEffect(() => {
    if (blockedReason !== null && waitingRef.current.ownsAttempt) {
      generationRef.current += 1;
      const inFlight = waitingRef.current.runId;
      if (inFlight !== null) {
        void releaseRun(client, inFlight, 'gate_closed');
      }
    }
    dispatch({ kind: 'gate_changed', blockedReason });
  }, [blockedReason, client]);

  // Reset practice remounts this panel under a new key rather than changing its
  // props, so a prop-driven cancel never runs for the burst the old panel left
  // behind. Unmount is the only signal that the run has lost its owner, and the
  // generation bump is what makes a submit still in flight cancel itself
  // instead of accepting into a panel that no longer exists.
  const clientRef = useRef(client);
  clientRef.current = client;
  useEffect(
    () => () => {
      generationRef.current += 1;
      const { mayBeLive: stillLive, runId: inFlight } = waitingRef.current;
      if (stillLive && inFlight !== null) {
        void releaseRun(clientRef.current, inFlight, 'panel_unmounted');
      }
    },
    [],
  );

  const request = useCallback(() => {
    if (blockedReason !== null || waiting || mediaId === null) {
      return;
    }
    // A timed-out run is stopped on screen only; the server may still be
    // burning GPU on it. Retrying without cancelling first is how one learner
    // gesture ends up paying for two live runs.
    //
    // Bump the generation first, so a gate close during the cancel round trip
    // still fences this attempt, and only then wait: cancellation is a request
    // the worker observes later, so issuing it in the same tick as the submit
    // guarantees nothing about ordering on a pool with room for one run. If the
    // server refuses the cancel we submit anyway -- stranding the learner with
    // a dead panel is the worse failure, and the rejection is now logged rather
    // than lost.
    const previous = mayBeLive && runId !== null ? runId : null;
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    attemptRef.current = 0;
    dispatch({ kind: 'requested', atMs: Date.now() });

    void (previous === null ? Promise.resolve() : releaseRun(client, previous, 'superseded_by_retry'))
      .then(() => {
        if (generationRef.current !== generation) {
          // The learner left while we were handing the old run back. Starting a
          // new burst for a panel that has moved on is exactly the spend this
          // whole path exists to prevent.
          return undefined;
        }
        return client.submit(mediaId);
      })
      .then((run) => {
        if (run === undefined) {
          return;
        }
        if (generationRef.current !== generation) {
          // The learner stopped waiting while the submit was in flight. The run
          // exists on the server now, so a burst it started keeps costing money
          // unless we cancel the run id we only just learned.
          void releaseRun(client, run.run_id, 'accepted_after_fence');
          return;
        }
        // The disclosed budget and the GPU state it was measured against
        // travel together: the reducer needs both to decide whether the
        // warm-up leg is still owed on top of the generation budget.
        const acceptedGpu = gpuStateOf(run.gpu_state);
        dispatch({
          kind: 'accepted',
          runId: run.run_id,
          deadlineSeconds: guidedLiveCeilingSecondsFor(acceptedGpu),
          gpu: acceptedGpu,
          disclosedDeadlineSeconds: run.deadline_seconds,
          atMs: Date.now(),
        });
      })
      .catch(() => {
        if (generationRef.current === generation) {
          dispatch({ kind: 'failed', reason: GUIDED_LIVE_REASON.SUBMIT_FAILED });
        }
      });
  }, [blockedReason, client, mayBeLive, mediaId, runId, waiting]);

  const cancel = useCallback(() => {
    if (!waiting) {
      return;
    }
    generationRef.current += 1;
    // The screen stops either way. A cancel the server never heard still leaves
    // the learner with a stopped wait rather than a spinner nobody owns.
    dispatch({ kind: 'cancelled' });
    if (runId !== null) {
      void releaseRun(client, runId, 'stopped_by_operator');
    }
  }, [client, runId, waiting]);

  useEffect(() => {
    if (!waiting) {
      return undefined;
    }
    const interval = setInterval(() => dispatch({ kind: 'tick', atMs: Date.now() }), TICK_MS);
    return () => clearInterval(interval);
  }, [waiting]);

  // The poll chain reschedules itself. Keying a `setTimeout` on `state.elapsedMs`
  // instead meant the 1s tick tore the timer down and re-armed it every second,
  // so once the backoff passed 1000ms the poll never fired at all and the run
  // sat in QUEUED until the client deadline. Fake timers hid it; a browser would
  // not have. Deps hold only the identity of the run being polled.
  useEffect(() => {
    if (!waiting || runId === null || mediaId === null) {
      return undefined;
    }
    const generation = generationRef.current;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const live = (): boolean => !cancelled && generationRef.current === generation;

    const schedule = (): void => {
      timer = setTimeout(() => void poll(), guidedLivePollDelayMs(attemptRef.current));
    };

    const poll = async (): Promise<void> => {
      try {
        const run = await client.poll(runId);
        if (!live()) {
          return;
        }
        const phase = phaseOf(run);
        if (phase === null) {
          // We cannot read this run any more, which is not the same as the run
          // being over. Stop polling AND hand it back, or the burst keeps the
          // pool with nobody watching it.
          void releaseRun(client, runId, 'unknown_phase');
          dispatch({ kind: 'failed', reason: GUIDED_LIVE_REASON.UNKNOWN_PHASE });
          return;
        }
        const gpu = gpuStateOf(run.gpu_state);

        if (phase !== DESCRIBE_RUN_PHASE.COMPLETE) {
          attemptRef.current += 1;
          // A submit-time warm pin can be wrong. If the run reports a colder GPU
          // than the pin assumed, give the wait back the warm-up leg it now
          // owes. This fires on every poll, disclosure or not: the reducer
          // re-derives the deadline from the same disclosed budget with the
          // newly owed warm-up leg and keeps the larger of the two, so it is
          // idempotent while a stale `gpu_state` at submit stays recoverable.
          dispatch({ kind: 'deadline_raised', deadlineSeconds: guidedLiveCeilingSecondsFor(gpu), gpu });
          dispatch({
            kind: 'polled',
            phase,
            gpu,
            atMs: Date.now(),
            disclosedDeadlineSeconds: run.deadline_seconds,
          });
          if (live()) {
            schedule();
          }
          return;
        }

        const draft = draftOf(await client.items(runId), mediaId);
        if (!live()) {
          return;
        }
        if (draft === null) {
          dispatch({
            kind: 'polled',
            phase,
            gpu,
            atMs: Date.now(),
            reason: GUIDED_LIVE_REASON.ITEM_MISSING,
            disclosedDeadlineSeconds: run.deadline_seconds,
          });
          return;
        }
        dispatch({
          kind: 'polled',
          phase,
          gpu,
          atMs: Date.now(),
          disclosedDeadlineSeconds: run.deadline_seconds,
          ...draft,
        });
      } catch (error) {
        if (!live()) {
          return;
        }
        if (!isFrozenPollFailure(error)) {
          // A hard failure will not heal by waiting. Say so now rather than
          // spending the learner's whole deadline on a dead channel -- but the
          // dead channel is the poll, not the run, so give the run back too.
          void releaseRun(client, runId, 'poll_failed');
          dispatch({ kind: 'failed', reason: GUIDED_LIVE_REASON.POLL_FAILED });
          return;
        }
        // Abort/timeout is transient: back off and retry inside the deadline the
        // tick already enforces.
        attemptRef.current += 1;
        dispatch({ kind: 'tick', atMs: Date.now() });
        schedule();
      }
    };

    schedule();
    return () => {
      cancelled = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  }, [client, mediaId, runId, waiting]);

  const keepWaiting = useCallback(() => {
    // No generation bump and no new submit: this is the same run, and the only
    // thing that stopped was this panel. Resetting the backoff makes the first
    // resumed poll immediate rather than five seconds late.
    attemptRef.current = 0;
    dispatch({ kind: 'wait_resumed', atMs: Date.now() });
  }, []);

  const disclosure = useMemo(() => guidedLiveNamingDisclosure(scenario), [scenario]);

  return {
    state,
    disclosure,
    blockedReason: state.blockedReason,
    canRequest: state.status !== GUIDED_LIVE_STATUS.BLOCKED && !waiting,
    canCancel: waiting,
    canKeepWaiting: state.status === GUIDED_LIVE_STATUS.TIMED_OUT && state.runId !== null,
    request,
    cancel,
    keepWaiting,
  };
};

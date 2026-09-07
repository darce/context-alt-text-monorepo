/**
 * Drives one bounded live describe run for the guided prototype.
 *
 * The reducer in `liveDescription.ts` owns every state transition; this hook
 * owns only the I/O and the clock. Keeping the split that way means the wait
 * bounds are testable without a network and the network is testable without
 * re-deriving the state machine.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';

import {
  cancelBulkDescribeRun,
  fetchBulkDescribeRun,
  fetchDescribeRunItems,
  isGpuState,
  submitBulkDescribeRun,
} from '../api/describeApi';
import type { DescribeRunItemsResponse, DescribeRunResponse } from '../api/describeApi';
import {
  GUIDED_LIVE_STATUS,
  GUIDED_LIVE_WAIT_CEILING_SECONDS,
  guidedLiveNamingDisclosure,
  guidedLivePollDelayMs,
  guidedLiveRequestPayload,
  guidedLiveReducer,
  initialGuidedLiveState,
  isGuidedLiveWaiting,
} from './liveDescription';
import type {
  GuidedLiveGpuState,
  GuidedLiveNamingDisclosure,
  GuidedLivePhase,
  GuidedLiveState,
  GuidedLiveTier,
} from './liveDescription';
import { confirmedPersonKeys } from './state';
import type { GuidedScenario } from './state';

/** Warm-GPU ceiling: the backend's own describe budget with no burst to pay for. */
export const GUIDED_LIVE_WARM_CEILING_SECONDS = 180;

const TICK_MS = 1000;

export interface GuidedLiveDescriptionClient {
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

export type GuidedLiveBlockedReason = 'no_faces_decided' | 'no_media';

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
  request: () => void;
  cancel: () => void;
}

const gpuStateOf = (value: unknown): GuidedLiveGpuState => (isGpuState(value) ? value : 'unknown');

const ceilingSecondsFor = (gpu: GuidedLiveGpuState): number =>
  gpu === 'ready' ? GUIDED_LIVE_WARM_CEILING_SECONDS : GUIDED_LIVE_WAIT_CEILING_SECONDS;

const phaseOf = (run: DescribeRunResponse): GuidedLivePhase => {
  switch (run.phase) {
    case 'complete':
    case 'failed':
    case 'cancelled':
    case 'warming':
    case 'describing':
      return run.phase;
    default:
      return 'queued';
  }
};

const draftOf = (
  items: DescribeRunItemsResponse,
  mediaId: number,
): { text: string | null; tier: GuidedLiveTier | null } => {
  const item = items.items.find((row) => row.media_id === mediaId) ?? items.items[0];
  return { text: item?.alt_text_draft ?? null, tier: item?.tier ?? null };
};

export const useGuidedLiveDescription = ({
  scenario,
  mediaId,
  client = defaultClient,
}: UseGuidedLiveDescriptionOptions): UseGuidedLiveDescriptionResult => {
  const [state, dispatch] = useReducer(guidedLiveReducer, undefined, initialGuidedLiveState);

  // A run generation fences every in-flight promise: a poll resolving after a
  // cancel or a new request must not write into the run that replaced it.
  const generationRef = useRef(0);
  const attemptRef = useRef(0);

  const facesDecided = confirmedPersonKeys(scenario).length > 0;
  const blockedReason: GuidedLiveBlockedReason | null = !facesDecided
    ? 'no_faces_decided'
    : mediaId === null
      ? 'no_media'
      : null;

  useEffect(() => {
    dispatch({ kind: 'faces_decided', decided: blockedReason === null });
  }, [blockedReason]);

  const waiting = isGuidedLiveWaiting(state.status);
  const runId = state.runId;

  const request = useCallback(() => {
    if (blockedReason !== null || waiting || mediaId === null) {
      return;
    }
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    attemptRef.current = 0;
    dispatch({ kind: 'requested', atMs: Date.now() });

    void client
      .submit(mediaId)
      .then((run) => {
        if (generationRef.current !== generation) {
          return;
        }
        dispatch({
          kind: 'accepted',
          runId: run.run_id,
          deadlineSeconds: ceilingSecondsFor(gpuStateOf(run.gpu_state)),
          atMs: Date.now(),
        });
      })
      .catch(() => {
        if (generationRef.current === generation) {
          dispatch({ kind: 'failed', reason: 'submit_failed' });
        }
      });
  }, [blockedReason, client, mediaId, waiting]);

  const cancel = useCallback(() => {
    if (!waiting) {
      return;
    }
    generationRef.current += 1;
    // The screen stops either way. A cancel the server never heard still leaves
    // the learner with a stopped wait rather than a spinner nobody owns.
    dispatch({ kind: 'cancelled' });
    if (runId !== null) {
      void client.cancel(runId).catch(() => undefined);
    }
  }, [client, runId, waiting]);

  useEffect(() => {
    if (!waiting) {
      return undefined;
    }
    const interval = setInterval(() => dispatch({ kind: 'tick', atMs: Date.now() }), TICK_MS);
    return () => clearInterval(interval);
  }, [waiting]);

  useEffect(() => {
    if (!waiting || runId === null || mediaId === null) {
      return undefined;
    }
    const generation = generationRef.current;
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const run = await client.poll(runId);
          if (generationRef.current !== generation) {
            return;
          }
          const phase = phaseOf(run);
          const gpu = gpuStateOf(run.gpu_state);

          if (phase !== 'complete') {
            attemptRef.current += 1;
            dispatch({ kind: 'polled', phase, gpu, atMs: Date.now() });
            return;
          }

          const draft = draftOf(await client.items(runId), mediaId);
          if (generationRef.current !== generation) {
            return;
          }
          dispatch({ kind: 'polled', phase, gpu, atMs: Date.now(), ...draft });
        } catch {
          if (generationRef.current === generation) {
            // A single failed poll is not a failed run; back off and retry
            // inside the deadline the tick already enforces.
            attemptRef.current += 1;
            dispatch({ kind: 'tick', atMs: Date.now() });
          }
        }
      })();
    }, guidedLivePollDelayMs(attemptRef.current));
    return () => clearTimeout(timer);
  }, [client, mediaId, runId, state.elapsedMs, state.status, waiting]);

  const disclosure = useMemo(() => guidedLiveNamingDisclosure(scenario), [scenario]);

  return {
    state,
    disclosure,
    blockedReason,
    canRequest: blockedReason === null && state.status !== GUIDED_LIVE_STATUS.BLOCKED && !waiting,
    canCancel: waiting,
    request,
    cancel,
  };
};

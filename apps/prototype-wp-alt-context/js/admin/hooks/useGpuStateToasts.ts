import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { GPU_STATE, type GpuState } from '../api/describeApi';
import { useToast } from '../context/ToastContext';
import { GPU_STATE_VOCABULARY } from '../pages/workbench/gpuStatePresentation';
import { useActiveDescribeRun } from './activeDescribeRun';
import { useDescribeRunProgress } from './useDescribeRunProgress';

const GPU_TOAST_EDGE = {
  WARMING: 'warming',
  READY: 'ready',
  DEGRADED: 'degraded',
} as const;

type GpuToastEdge = (typeof GPU_TOAST_EDGE)[keyof typeof GPU_TOAST_EDGE];

export const useGpuStateToasts = (): void => {
  const navigate = useNavigate();
  const { info, error } = useToast();
  const { runId, progressMounted } = useActiveDescribeRun();
  const progress = useDescribeRunProgress(runId);
  const rememberedRunIdRef = useRef<string | null>(null);
  const previousStateRef = useRef<GpuState | null>(null);
  const emittedEdgesRef = useRef(new Set<GpuToastEdge>());

  useEffect(() => {
    if (rememberedRunIdRef.current !== runId) {
      rememberedRunIdRef.current = runId;
      previousStateRef.current = null;
      emittedEdgesRef.current.clear();
    }

    if (runId === null || progress.run?.run_id !== runId) {
      return;
    }

    const nextState = progress.gpuState ?? GPU_STATE.UNKNOWN;
    const previousState = previousStateRef.current;
    previousStateRef.current = nextState;

    // A first observation is a snapshot, not an edge. Unknown is likewise a
    // first-class absence of lifecycle evidence and never creates an event.
    if (previousState === null || previousState === GPU_STATE.UNKNOWN || nextState === GPU_STATE.UNKNOWN) {
      return;
    }

    if (nextState === GPU_STATE.DEGRADED && previousState !== GPU_STATE.DEGRADED) {
      if (!emittedEdgesRef.current.has(GPU_TOAST_EDGE.DEGRADED)) {
        emittedEdgesRef.current.add(GPU_TOAST_EDGE.DEGRADED);
        error(GPU_STATE_VOCABULARY.degradedToast, {
          action: {
            label: GPU_STATE_VOCABULARY.reviewResults,
            altText: GPU_STATE_VOCABULARY.reviewResultsAltText,
            onClick: () => {
              void navigate('/workbench');
            },
          },
          durationMs: null,
        });
      }
      return;
    }

    if (progressMounted) {
      return;
    }

    if (
      nextState === GPU_STATE.WARMING &&
      (previousState === GPU_STATE.STOPPED || previousState === GPU_STATE.STARTING) &&
      !emittedEdgesRef.current.has(GPU_TOAST_EDGE.WARMING)
    ) {
      emittedEdgesRef.current.add(GPU_TOAST_EDGE.WARMING);
      info(GPU_STATE_VOCABULARY.warmingToast);
      return;
    }

    if (
      previousState === GPU_STATE.WARMING &&
      nextState === GPU_STATE.READY &&
      !emittedEdgesRef.current.has(GPU_TOAST_EDGE.READY)
    ) {
      emittedEdgesRef.current.add(GPU_TOAST_EDGE.READY);
      info(GPU_STATE_VOCABULARY.readyToast, {
        action: {
          label: GPU_STATE_VOCABULARY.backToRun,
          altText: GPU_STATE_VOCABULARY.backToRunAltText,
          onClick: () => {
            void navigate('/workbench');
          },
        },
        durationMs: null,
      });
    }
  }, [error, info, navigate, progress.gpuState, progress.run, progressMounted, runId]);
};

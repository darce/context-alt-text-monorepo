import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

import { GPU_STATE, type GpuState } from '../api/describeApi';
import { useToast } from '../context/ToastContext';
import { GPU_STATE_VOCABULARY } from '../pages/workbench/gpuStatePresentation';
import { useActiveDescribeRun } from './activeDescribeRun';
import {
  ACTIVITY_KIND,
  ACTIVITY_REASON,
  useActivityStatus,
  type ActivityKind,
} from './useActivityStatus';

const GPU_TOAST_EDGE = {
  WARMING: 'warming',
  READY: 'ready',
  DONE: 'done',
  FAILED: 'failed',
  DEGRADED: 'degraded',
} as const;

type GpuToastEdge = (typeof GPU_TOAST_EDGE)[keyof typeof GPU_TOAST_EDGE];

const pathFromAppHref = (href: string): string => (href.startsWith('#') ? href.slice(1) : href);

const failedToastMessage = (reason: string | null): string => {
  switch (reason) {
    case ACTIVITY_REASON.GPU_WARMUP_TIMEOUT:
      return GPU_STATE_VOCABULARY.failedToastWarmupTimeout;
    case ACTIVITY_REASON.DESCRIBE_POLL_ERROR:
      return GPU_STATE_VOCABULARY.failedToastDescribePoll;
    case ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE:
      return GPU_STATE_VOCABULARY.failedToastGpuUnavailable;
    case ACTIVITY_REASON.CANCELLED:
      return GPU_STATE_VOCABULARY.failedToastCancelled;
    case ACTIVITY_REASON.SCAN_FAILED:
      return GPU_STATE_VOCABULARY.failedToastScanFailed;
    case ACTIVITY_REASON.FAILED:
      return GPU_STATE_VOCABULARY.failedToastFailed;
    default:
      return reason !== null && reason !== ''
        ? GPU_STATE_VOCABULARY.failedToastWithReason(reason)
        : GPU_STATE_VOCABULARY.failedToastGeneric;
  }
};

export const useGpuStateToasts = (): void => {
  const navigate = useNavigate();
  const { success, info, error } = useToast();
  const { progressMounted } = useActiveDescribeRun();
  const { status, actions } = useActivityStatus();
  const rememberedRunIdRef = useRef<string | null>(null);
  const previousKindRef = useRef<ActivityKind | null>(null);
  const previousGpuStateRef = useRef<GpuState | null>(null);
  const emittedEdgesRef = useRef(new Set<GpuToastEdge>());

  useEffect(() => {
    if (rememberedRunIdRef.current !== status.runId) {
      rememberedRunIdRef.current = status.runId;
      previousKindRef.current = null;
      previousGpuStateRef.current = null;
      emittedEdgesRef.current.clear();
    }

    const previousKind = previousKindRef.current;
    const nextKind = status.kind;
    previousKindRef.current = nextKind;

    const nextGpu = status.gpuState ?? GPU_STATE.UNKNOWN;
    const previousGpu = previousGpuStateRef.current;
    previousGpuStateRef.current = nextGpu;

    if (previousKind === null) {
      return;
    }

    const emit = (edge: GpuToastEdge, fire: () => void): void => {
      if (emittedEdgesRef.current.has(edge)) {
        return;
      }
      emittedEdgesRef.current.add(edge);
      fire();
    };

    if (
      nextGpu === GPU_STATE.DEGRADED &&
      previousGpu !== GPU_STATE.DEGRADED &&
      previousGpu !== GPU_STATE.UNKNOWN
    ) {
      emit(GPU_TOAST_EDGE.DEGRADED, () => {
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
      });
      return;
    }

    if (progressMounted || nextKind === previousKind) {
      return;
    }

    if (nextKind === ACTIVITY_KIND.WARMING) {
      emit(GPU_TOAST_EDGE.WARMING, () => {
        info(GPU_STATE_VOCABULARY.warmingToast);
      });
      return;
    }

    if (nextKind === ACTIVITY_KIND.DESCRIBING && previousKind === ACTIVITY_KIND.WARMING) {
      const backToRunHref = actions.backToRunHref;
      emit(GPU_TOAST_EDGE.READY, () => {
        info(GPU_STATE_VOCABULARY.readyToast, {
          action: {
            label: GPU_STATE_VOCABULARY.backToRun,
            altText: GPU_STATE_VOCABULARY.backToRunAltText,
            onClick: () => {
              void navigate(backToRunHref === null ? '/workbench' : pathFromAppHref(backToRunHref));
            },
          },
          durationMs: null,
        });
      });
      return;
    }

    if (nextKind === ACTIVITY_KIND.DONE) {
      const reviewHref = actions.reviewDraftsHref;
      const draftCount = status.draftCount;
      emit(GPU_TOAST_EDGE.DONE, () => {
        success(GPU_STATE_VOCABULARY.doneToast(draftCount), {
          action: {
            label: GPU_STATE_VOCABULARY.reviewDrafts(draftCount),
            altText: GPU_STATE_VOCABULARY.reviewDraftsAltText,
            onClick: () => {
              if (reviewHref === null) {
                return;
              }
              void navigate(pathFromAppHref(reviewHref));
            },
          },
          durationMs: null,
        });
      });
      return;
    }

    if (nextKind === ACTIVITY_KIND.FAILED) {
      const onRetry = status.retryable ? actions.onRetry : null;
      emit(GPU_TOAST_EDGE.FAILED, () => {
        error(failedToastMessage(status.reason), {
          action:
            onRetry === null
              ? undefined
              : {
                  label: GPU_STATE_VOCABULARY.retry,
                  altText: GPU_STATE_VOCABULARY.retryAltText,
                  onClick: onRetry,
                },
          durationMs: null,
        });
      });
    }
  }, [actions, error, info, navigate, progressMounted, status, success]);
};

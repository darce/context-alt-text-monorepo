import { useCallback, useEffect, useRef, useState } from 'react';
import { __ } from '@wordpress/i18n';

import type { ClusterResponse } from '../api/recognition';
import { resolveScanErrorMessage } from '../api/recognition/scanApiError';
import { classifyError } from '../utils/appError';
import {
  createLogger,
  logJobEvent,
  newRequestId,
  redactEndpoint,
  withRequestId,
  type LogFields,
  type Logger,
} from '../utils/logger';
import { createClusterAutoRetry } from './clusterAutoRetry';
import type { JobType } from './useJobPersistence';
import { useScanIdentities, useClusterIdentities, useCancelScanJobs } from './useRecognitionHooks';

const log = createLogger('jobStateMachineMutations');

/**
 * Endpoint redaction has exactly one owner (REF-19/REF-21, FEBT-1-W1-O-06): this used to
 * hold a private `new URL(...).pathname` redactor, i.e. a second copy of a PII rule that
 * failed OPEN and drifted away from the logger's. It now delegates to `redactEndpoint`.
 */
const classifiedLogFields = (error: unknown): LogFields => {
  const classified = classifyError(error);
  const fields: LogFields = { tag: classified._tag };
  if ('status' in classified) {
    fields.status = classified.status;
  }
  if ('endpoint' in classified) {
    fields.endpoint = redactEndpoint(classified.endpoint);
  }
  return fields;
};

interface JobStateMachineMutationOptions {
  activeJobIds: string[];
  addJob: (id: string, type: JobType, totalItems: number, batchRunId?: string) => void;
  removeJob: (id: string) => void;
  setIsWaitingForScanCompletion: (value: boolean) => void;
  setIsCancellingScan: (value: boolean) => void;
  setActiveBatchRunId: (value: string | null) => void;
  invalidateIdentities: () => void;
  onScanStart?: () => void;
  onScanComplete?: (jobIds: string[]) => void;
  onScanError?: (message: string) => void;
  onClusterComplete?: (data: ClusterResponse) => void;
  onClusterError?: (message: string) => void;
  onCancelComplete?: () => void;
}

export const useJobStateMachineMutations = ({
  activeJobIds,
  addJob,
  removeJob,
  setIsWaitingForScanCompletion,
  setIsCancellingScan,
  setActiveBatchRunId,
  invalidateIdentities,
  onScanStart,
  onScanComplete,
  onScanError,
  onClusterComplete,
  onClusterError,
  onCancelComplete,
}: JobStateMachineMutationOptions) => {
  const clearActiveJobs = useCallback(() => {
    activeJobIds.forEach((id) => removeJob(id));
  }, [activeJobIds, removeJob]);

  // One correlation id per unit of work, minted when the action starts and reused by its
  // outcome handler so submit/success and submit/failure share a grep key (OBS-03).
  const scanRequestIdRef = useRef<string | null>(null);
  const cancelRequestIdRef = useRef<string | null>(null);
  // The submit unit's correlation id, pinned to the job ids that submit actually created
  // (OBS-03). Membership is half the pin: a job that this submit did not create — one
  // rehydrated from persistence, or the next submit's — must resolve to "unknown" and mint
  // its own id. A fabricated join is worse than an absent one, because it makes a grep
  // return a confident wrong answer instead of nothing (ml CAL-02: unknown is a valid
  // result; rg-015: adapters do not invent contract metadata).
  const scanCorrelationRef = useRef<{ requestId: string; jobIds: readonly string[] } | null>(null);
  const scanLog = useCallback(
    (): Logger => withRequestId(log, scanRequestIdRef.current ?? newRequestId()),
    [],
  );
  const cancelLog = useCallback(
    (): Logger => withRequestId(log, cancelRequestIdRef.current ?? newRequestId()),
    [],
  );

  const [clusterQueuedSeconds, setClusterQueuedSeconds] = useState<number | null>(null);
  const [canRetryClustering, setCanRetryClustering] = useState(false);

  const onClusterCompleteRef = useRef(onClusterComplete);
  const onClusterErrorRef = useRef(onClusterError);
  useEffect(() => {
    onClusterCompleteRef.current = onClusterComplete;
    onClusterErrorRef.current = onClusterError;
  }, [onClusterComplete, onClusterError]);

  const scanMutation = useScanIdentities({
    onMutate: () => {
      scanRequestIdRef.current = newRequestId();
      // The previous submit's pin is dead the moment a new submit starts: leaving it live
      // would correlate the old batch's stream lines to the new submit.
      scanCorrelationRef.current = null;
      onScanStart?.();
      clearActiveJobs();
      setIsWaitingForScanCompletion(false);
      setActiveBatchRunId(null);
    },
    onSuccess: (data) => {
      setActiveBatchRunId(data.batchRunId);
      const jobIds = data.jobs.map((job) => job.id).filter((id): id is string => Boolean(id));
      const total = data.jobs.reduce((sum, job) => sum + (job.progress?.total ?? 0), 0);
      // Membership is the only gate. An explicit `jobIds.length > 0` clause here was dead:
      // an empty batch pins an empty id list, which `includes()` already disclaims for every
      // job, so the two gates masked each other and no mutant could tell them apart.
      const submitRequestId = scanRequestIdRef.current;
      scanCorrelationRef.current = submitRequestId === null ? null : { requestId: submitRequestId, jobIds };
      if (jobIds.length > 0) {
        data.jobs.forEach((job) => {
          if (!job.id) {
            return;
          }
          addJob(job.id, 'scan', job.progress?.total ?? 0, data.batchRunId);
        });
        setIsWaitingForScanCompletion(true);
      } else {
        setIsWaitingForScanCompletion(false);
      }
      invalidateIdentities();
      onScanComplete?.(jobIds);
      // Correlation must cover the whole batch: binding only to jobIds[0] left every other
      // job's later sse.* / stream.done lines unjoinable to this submit (OBS-03, FEBT1-W2B-02).
      const jobId = jobIds[0];
      const batchLog = scanLog().child({ jobIds, jobCount: jobIds.length, batchRunId: data.batchRunId });
      const jobLog = jobId ? batchLog.child({ jobId }) : batchLog;
      logJobEvent(jobLog, 'scan.submit', {
        status: jobIds.length > 0 ? 'pending' : 'completed',
        jobId,
        done: 0,
        total,
        failedCount: 0,
      });
      // Every job in the batch gets its own correlation line so the later per-job
      // sse.* / stream.done records can be joined back to this submit (OBS-03).
      data.jobs.forEach((job) => {
        if (!job.id) {
          return;
        }
        batchLog.child({ jobId: job.id }).debug('scan.submit_job', {
          batchRunId: data.batchRunId,
          total: job.progress?.total ?? 0,
        });
      });
    },
    onError: (error) => {
      const failedLog = scanLog();
      failedLog.error('Scan submission failed', classifiedLogFields(error));
      logJobEvent(failedLog, 'scan.submit', {
        status: 'failed',
        failedCount: 1,
      });
      onScanError?.(resolveScanErrorMessage(error, __('Recognition job failed. Please try again.', 'alt-context')));
    },
  });

  const mutateClusterRef = useRef<() => void>(() => {
    // Placeholder until createCluster is assigned below; replaced on each render.
  });

  const retryControllerRef = useRef(
    createClusterAutoRetry({
      mutate: () => {
        mutateClusterRef.current();
      },
      onQueued: (seconds) => {
        setClusterQueuedSeconds(seconds);
      },
      onExhausted: () => {
        setCanRetryClustering(true);
      },
      onTerminalError: (message) => {
        onClusterErrorRef.current?.(message);
      },
      fallbackErrorMessage: __('Clustering failed. Please try again.', 'alt-context'),
    }),
  );

  useEffect(
    () => () => {
      retryControllerRef.current.dispose();
    },
    [],
  );

  const clusterMutation = useClusterIdentities({
    onSuccess: (data) => {
      retryControllerRef.current.noteSuccess();
      setCanRetryClustering(false);
      if (data.id && data.status === 'pending') {
        addJob(data.id, 'clustering', data.total_identities_clustered || 0);
        return;
      }
      invalidateIdentities();
      onClusterCompleteRef.current?.(data);
    },
    onError: (error) => {
      // 429: auto-retry up to CLUSTER_RETRY_MAX_ATTEMPTS (MutationCache arms shared cooldown).
      // Non-429 / ceiling: controller surfaces onTerminalError; never blind-retry other 4xx.
      retryControllerRef.current.noteError(error);
    },
  });

  // Keep the ref current during render so start/retry never hit a stale no-op.
  mutateClusterRef.current = () => {
    clusterMutation.mutate();
  };

  const startCluster = useCallback(() => {
    setCanRetryClustering(false);
    retryControllerRef.current.start();
  }, []);

  const retryClustering = useCallback(() => {
    setCanRetryClustering(false);
    retryControllerRef.current.manualRetry();
  }, []);

  const cancelMutation = useCancelScanJobs({
    onMutate: () => {
      cancelRequestIdRef.current = newRequestId();
      setIsCancellingScan(true);
    },
    onSuccess: () => {
      const jobId = activeJobIds[0];
      const base = cancelLog();
      const jobLog = jobId ? base.child({ jobId }) : base;
      logJobEvent(jobLog, 'scan.cancel', {
        status: 'cancelled',
        jobId,
      });
      setIsWaitingForScanCompletion(false);
      clearActiveJobs();
      // FEBT2-W2-T-02 (RES-07): the batch-run id is the last thing keeping the run alive.
      // `clearActiveJobs()` only drops the jobs, and useJobStateMachine falls back
      // `activeBatchRunId ?? latestScanJob?.batchRunId`, so a retained id kept
      // `useBatchRunStatus(batchRunId, Boolean(batchRunId))` polling forever against a run
      // that no longer exists. The scan's own `onMutate` already clears it on start; a
      // cancel is the other exit from the run and must reclaim it too.
      setActiveBatchRunId(null);
      invalidateIdentities();
      onCancelComplete?.();
    },
    onError: (error) => {
      const jobId = activeJobIds[0];
      const base = cancelLog();
      const jobLog = jobId ? base.child({ jobId }) : base;
      jobLog.error('Cancel failed', classifiedLogFields(error));
      logJobEvent(jobLog, 'scan.cancel', {
        status: 'failed',
        jobId,
        failedCount: 1,
      });
    },
    onSettled: () => {
      setIsCancellingScan(false);
    },
  });

  /**
   * The seam that lets one grep span scan-submit -> SSE (FEBT2-LB-NEW-03). Returns the
   * submit unit's requestId when `jobId` is one this submit created, and `null` when the
   * ownership is unknown so the caller mints a fresh id instead of inheriting a stale one.
   */
  const resolveScanRequestId = useCallback((jobId: string): string | null => {
    const pinned = scanCorrelationRef.current;
    if (!pinned?.jobIds.includes(jobId)) {
      return null;
    }
    return pinned.requestId;
  }, []);

  return {
    scanMutation,
    clusterMutation,
    cancelMutation,
    resolveScanRequestId,
    startCluster,
    retryClustering,
    clusterQueuedSeconds,
    canRetryClustering,
  };
};

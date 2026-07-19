import { useCallback, useEffect, useRef, useState } from 'react';
import { __ } from '@wordpress/i18n';

import type { ClusterResponse } from '../api/recognition';
import { formatScanSubmissionError, resolveScanErrorMessage } from '../api/recognition/scanApiError';
import { createClusterAutoRetry } from './clusterAutoRetry';
import type { JobType } from './useJobPersistence';
import { useScanIdentities, useClusterIdentities, useCancelScanJobs } from './useRecognitionHooks';

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
      onScanStart?.();
      clearActiveJobs();
      setIsWaitingForScanCompletion(false);
      setActiveBatchRunId(null);
    },
    onSuccess: (data) => {
      setActiveBatchRunId(data.batchRunId);
      const jobIds = data.jobs.map((job) => job.id).filter((id): id is string => Boolean(id));
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
    },
    onError: (error) => {
      if (!formatScanSubmissionError(error) && error instanceof Error) {
        // Non-JSON proxy/HTTP error bodies must not reach the UI (E15-27-BR-11).
        console.error('Scan submission failed', error);
      }
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
      setIsCancellingScan(true);
    },
    onSuccess: () => {
      setIsWaitingForScanCompletion(false);
      clearActiveJobs();
      invalidateIdentities();
      onCancelComplete?.();
    },
    onError: (error) => {
      console.error('Cancel failed', error);
    },
    onSettled: () => {
      setIsCancellingScan(false);
    },
  });

  return {
    scanMutation,
    clusterMutation,
    cancelMutation,
    startCluster,
    retryClustering,
    clusterQueuedSeconds,
    canRetryClustering,
  };
};

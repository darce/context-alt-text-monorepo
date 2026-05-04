import { useCallback } from 'react';
import { __ } from '@wordpress/i18n';

import type { ClusterResponse } from '../api/recognition';
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
      const message =
        error instanceof Error ? error.message : __('Recognition job failed. Please try again.', 'alt-context');
      onScanError?.(message);
    },
  });

  const clusterMutation = useClusterIdentities({
    onSuccess: (data) => {
      if (data.id && data.status === 'pending') {
        addJob(data.id, 'clustering', data.total_identities_clustered || 0);
        return;
      }
      invalidateIdentities();
      onClusterComplete?.(data);
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : __('Clustering failed. Please try again.', 'alt-context');
      onClusterError?.(message);
    },
  });

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

  return { scanMutation, clusterMutation, cancelMutation };
};

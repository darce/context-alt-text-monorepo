import { useEffect } from 'react';
import { queryKeys } from '../api/queryKeys';
import type { JobStatusResponse } from '../api/recognition/types/scan';
import type { JobPhase } from './jobStateMachineUtils';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';
import type { QueryClient } from '@tanstack/react-query';

interface JobStateMachineEffectsOptions {
  scanStatus: JobStatusResponse | undefined;
  queryClient: QueryClient;
  activeJobIds: string[];
  activeJobs: PersistedJob[];
  isWaitingForScanCompletion: boolean;
  setIsWaitingForScanCompletion: (value: boolean) => void;
  latestScanJob: PersistedJob | null;
  sseStatus: JobStatus;
  removeJob: (id: string) => void;
  cluster: () => void;
  latestClusterJob: PersistedJob | null;
  currentPhase: JobPhase;
}

export const useJobStateMachineEffects = ({
  scanStatus,
  queryClient,
  activeJobIds,
  activeJobs,
  isWaitingForScanCompletion,
  setIsWaitingForScanCompletion,
  latestScanJob,
  sseStatus,
  removeJob,
  cluster,
  latestClusterJob,
  currentPhase,
}: JobStateMachineEffectsOptions) => {
  useEffect(() => {
    if (scanStatus?.status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
    }
  }, [scanStatus?.status, queryClient]);

  useEffect(() => {
    if (!isWaitingForScanCompletion || activeJobIds.length === 0) {
      return;
    }

    const completed = sseStatus === 'completed' || sseStatus === 'failed';

    if (completed && latestScanJob) {
      setIsWaitingForScanCompletion(false);
      activeJobs.filter((job) => job.type === 'scan').forEach((job) => removeJob(job.id));
      cluster();
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
    }
  }, [
    sseStatus,
    activeJobIds,
    activeJobs,
    latestScanJob,
    isWaitingForScanCompletion,
    removeJob,
    cluster,
    queryClient,
    setIsWaitingForScanCompletion,
  ]);

  useEffect(() => {
    if (!latestClusterJob) {
      return;
    }

    const clusteringCompleted = sseStatus === 'completed' || sseStatus === 'failed';
    if (clusteringCompleted && currentPhase === 'clustering') {
      removeJob(latestClusterJob.id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    }
  }, [sseStatus, currentPhase, latestClusterJob, queryClient, removeJob]);
};

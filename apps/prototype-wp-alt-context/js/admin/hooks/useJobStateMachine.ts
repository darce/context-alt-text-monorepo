import { useCallback, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import type { ClusterResponse } from '../api/recognition';
import {
  buildScanProgress,
  buildStatusText,
  deriveJobPhase,
  deriveLatestJobId,
  getLatestJobByType,
  isScanRunning as getIsScanRunning,
  type JobPhase,
} from './jobStateMachineUtils';
import { useJobStateMachineEffects } from './useJobStateMachineEffects';
import { useJobStateMachineMutations } from './useJobStateMachineMutations';
import { useJobPersistence } from './useJobPersistence';
import { useJobProgressStream } from './useJobProgressStream';
import { useCombinedScanStatus } from './useRecognitionHooks';

export type { JobPhase } from './jobStateMachineUtils';

export interface JobStateMachineOptions {
  onScanStart?: () => void;
  onScanComplete?: (jobIds: string[]) => void;
  onScanError?: (message: string) => void;
  onClusterComplete?: (data: ClusterResponse) => void;
  onClusterError?: (message: string) => void;
  onCancelComplete?: () => void;
  jobId?: string | null; // For history polling
}

export const useJobStateMachine = ({
  onScanStart,
  onScanComplete,
  onScanError,
  onClusterComplete,
  onClusterError,
  onCancelComplete,
  jobId,
}: JobStateMachineOptions = {}) => {
  const queryClient = useQueryClient();
  const { activeJobs, addJob, removeJob } = useJobPersistence();
  const activeJobIds = useMemo(() => activeJobs.map((j) => j.id), [activeJobs]);

  const [isWaitingForScanCompletion, setIsWaitingForScanCompletion] = useState(false);
  const [isCancellingScan, setIsCancellingScan] = useState(false);

  const invalidateIdentities = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  }, [queryClient]);

  const { scanMutation, clusterMutation, cancelMutation } = useJobStateMachineMutations({
    activeJobIds,
    addJob,
    removeJob,
    setIsWaitingForScanCompletion,
    setIsCancellingScan,
    invalidateIdentities,
    onScanStart,
    onScanComplete,
    onScanError,
    onClusterComplete,
    onClusterError,
    onCancelComplete,
  });

  // Track jobs by type
  const latestScanJob = useMemo(() => getLatestJobByType(activeJobs, 'scan'), [activeJobs]);
  const latestClusterJob = useMemo(() => getLatestJobByType(activeJobs, 'clustering'), [activeJobs]);

  // Derive phase
  const currentPhase = useMemo<JobPhase>(
    () => deriveJobPhase(latestScanJob, latestClusterJob),
    [latestScanJob, latestClusterJob],
  );

  // SSE Stream
  const latestJobId = useMemo(
    () => deriveLatestJobId(currentPhase, latestScanJob, latestClusterJob),
    [currentPhase, latestScanJob, latestClusterJob],
  );

  const {
    progress: sseProgress,
    status: sseStatus,
    isOnline,
    etaSeconds,
    isPrimary,
  } = useJobProgressStream(latestJobId);

  // Poll for history / external updates
  const { scanStatusQuery } = useCombinedScanStatus(jobId ?? null, []);

  useJobStateMachineEffects({
    scanStatus: scanStatusQuery.data,
    queryClient,
    activeJobIds,
    activeJobs,
    isWaitingForScanCompletion,
    setIsWaitingForScanCompletion,
    latestScanJob,
    sseStatus,
    removeJob,
    cluster: () => clusterMutation.mutate(),
    latestClusterJob,
    currentPhase,
  });

  // Status Text
  const statusText = useMemo(
    () =>
      buildStatusText({
        clusterPending: clusterMutation.isPending,
        sseStatus,
        sseProgress,
        activeJobIds,
        scanStatus: scanStatusQuery.data,
        latestJobId,
        scanPending: scanMutation.isPending,
      }),
    [
      activeJobIds,
      clusterMutation.isPending,
      sseProgress,
      sseStatus,
      latestJobId,
      scanMutation.isPending,
      scanStatusQuery.data,
    ],
  );

  // Progress aggregation
  const scanProgress = useMemo(
    () =>
      buildScanProgress({
        activeJobIds,
        activeJobs,
        sseProgress,
        latestScanJob,
        fallbackProgress: scanStatusQuery.data?.progress,
      }),
    [activeJobIds, activeJobs, sseProgress, latestScanJob, scanStatusQuery.data?.progress],
  );

  const isScanRunning = useMemo(
    () =>
      getIsScanRunning({
        scanPending: scanMutation.isPending,
        waitingForCompletion: isWaitingForScanCompletion,
        activeJobIds,
        sseStatus,
        scanStatus: scanStatusQuery.data,
      }),
    [activeJobIds, isWaitingForScanCompletion, scanMutation.isPending, scanStatusQuery.data, sseStatus],
  );

  return {
    // State
    currentPhase,
    latestJobId,
    activeJobIds,
    isScanRunning,
    isCancellingScan,
    statusText,
    scanProgress,
    sseStatus,
    sseProgress,
    isOnline,
    etaSeconds,
    isPrimary,

    // Actions
    scan: scanMutation.mutate,
    cancelScan: cancelMutation.mutate,
    cluster: clusterMutation.mutate,
  };
};

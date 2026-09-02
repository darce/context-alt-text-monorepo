import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import type { ClusterResponse } from '../api/recognition';
import { isHttpStatus } from '../utils/appError';
import { useSyncTrigger } from './useSyncTrigger';
import { derivePipelinePhase, deriveLatestJobId, getLatestJobByType, type PipelinePhase } from './jobStateMachineUtils';
import { useJobStateMachineDerivedState } from './useJobStateMachineDerivedState';
import { useJobStateMachineEffects, type ProjectionSyncState } from './useJobStateMachineEffects';
import { useJobStateMachineMutations } from './useJobStateMachineMutations';
import { useJobPersistence } from './useJobPersistence';
import { useJobProgressStream } from './useJobProgressStream';
import { useCombinedScanStatus } from './useRecognitionHooks';

export type { PipelinePhase } from './jobStateMachineUtils';

export interface JobStateMachineOptions {
  onScanStart?: () => void;
  onScanComplete?: (jobIds: string[]) => void;
  onScanError?: (message: string) => void;
  onClusterComplete?: (data: ClusterResponse) => void;
  onClusterError?: (message: string) => void;
  onCancelComplete?: () => void;
  jobId?: string | null; // For history polling
  onJobNotFound?: (jobId: string) => void;
}

export const useJobStateMachine = ({
  onScanStart,
  onScanComplete,
  onScanError,
  onClusterComplete,
  onClusterError,
  onCancelComplete,
  jobId,
  onJobNotFound,
}: JobStateMachineOptions = {}) => {
  const queryClient = useQueryClient();
  const { activeJobs, addJob, removeJob } = useJobPersistence();
  const activeJobIds = useMemo(() => activeJobs.map((j) => j.id), [activeJobs]);

  const [isWaitingForScanCompletion, setIsWaitingForScanCompletion] = useState(false);
  const [isCancellingScan, setIsCancellingScan] = useState(false);
  const [activeBatchRunId, setActiveBatchRunId] = useState<string | null>(null);
  const [projectionSyncState, setProjectionSyncState] = useState<ProjectionSyncState>('idle');
  const [projectionError, setProjectionError] = useState<string | null>(null);
  const [projectionSyncNonce, setProjectionSyncNonce] = useState(0);

  const invalidateIdentities = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  }, [queryClient]);

  const {
    scanMutation,
    clusterMutation,
    cancelMutation,
    startCluster,
    retryClustering,
    clusterQueuedSeconds,
    canRetryClustering,
  } = useJobStateMachineMutations({
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
  });

  // Track jobs by type
  const latestScanJob = useMemo(() => getLatestJobByType(activeJobs, 'scan'), [activeJobs]);
  const latestClusterJob = useMemo(() => getLatestJobByType(activeJobs, 'clustering'), [activeJobs]);
  const batchRunId = activeBatchRunId ?? latestScanJob?.batchRunId ?? null;

  // Poll for history / external updates
  const {
    scanStatusQuery,
    multiScanStatus = [],
    batchRunStatusQuery,
  } = useCombinedScanStatus(jobId ?? null, activeJobIds, batchRunId);

  useEffect(() => {
    if (!jobId) {
      return;
    }
    if (isHttpStatus(scanStatusQuery.error, 404)) {
      onJobNotFound?.(jobId);
    }
  }, [jobId, onJobNotFound, scanStatusQuery.error]);

  useEffect(() => {
    if (activeJobIds.length === 0) {
      return;
    }

    multiScanStatus.forEach((statusQuery, index) => {
      const staleJobId = activeJobIds[index];
      if (staleJobId && isHttpStatus(statusQuery.error, 404)) {
        removeJob(staleJobId);
      }
    });
  }, [activeJobIds, multiScanStatus, removeJob]);

  // Derive phase
  const currentPhase = useMemo<PipelinePhase>(
    () => derivePipelinePhase(latestScanJob, latestClusterJob, scanStatusQuery.data, batchRunStatusQuery.data),
    [batchRunStatusQuery.data, latestScanJob, latestClusterJob, scanStatusQuery.data],
  );

  // SSE Stream
  const latestJobId = useMemo(
    () => deriveLatestJobId(currentPhase, latestScanJob, latestClusterJob, scanStatusQuery.data),
    [currentPhase, latestScanJob, latestClusterJob, scanStatusQuery.data],
  );

  const {
    progress: sseProgress,
    status: sseStatus,
    isOnline,
    etaSeconds,
    isPrimary,
    stalledForSeconds,
    retry: retryScanStream,
  } = useJobProgressStream(latestJobId);
  const syncTrigger = useSyncTrigger(false);

  useJobStateMachineEffects({
    scanStatus: scanStatusQuery.data,
    batchRunStatus: batchRunStatusQuery.data,
    queryClient,
    activeJobs,
    isWaitingForScanCompletion,
    setIsWaitingForScanCompletion,
    sseStatus,
    removeJob,
    cluster: startCluster,
    latestClusterJob,
    currentPhase,
    syncTrigger,
    projectionSyncState,
    projectionSyncNonce,
    setProjectionSyncState,
    setProjectionError,
  });

  const { statusText, scanProgress, clusterProgress, isScanRunning, scanStallSeconds } = useJobStateMachineDerivedState(
    {
      currentPhase,
      activeJobIds,
      activeJobs,
      latestScanJob,
      latestJobId,
      scanPending: scanMutation.isPending,
      clusterPending: clusterMutation.isPending,
      clusterQueuedSeconds,
      waitingForCompletion: isWaitingForScanCompletion,
      scanStatus: scanStatusQuery.data,
      batchRunStatus: batchRunStatusQuery.data,
      sseStatus,
      sseProgress,
      stalledForSeconds,
    },
  );

  const handleScan = useCallback(
    (mediaIds: number[]) => {
      setProjectionSyncState('idle');
      setProjectionError(null);
      setProjectionSyncNonce(0);
      scanMutation.mutate(mediaIds);
    },
    [scanMutation],
  );

  const retryProjectionSync = useCallback(() => {
    setProjectionError(null);
    setProjectionSyncNonce((value) => value + 1);
  }, []);

  return {
    // State
    currentPhase,
    latestJobId,
    activeJobIds,
    isScanRunning,
    isCancellingScan,
    projectionSyncState,
    projectionError,
    statusText,
    scanProgress,
    clusterProgress,
    batchRunStatus: batchRunStatusQuery.data ?? null,
    scanStallSeconds,
    sseStatus,
    sseProgress,
    isOnline,
    etaSeconds,
    isPrimary,

    // Actions
    scan: handleScan,
    cancelScan: cancelMutation.mutate,
    cluster: startCluster,
    retryClustering,
    canRetryClustering,
    retryProjectionSync,
    retryScanStream,
  };
};

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import type { ClusterResponse } from '../api/recognition';
import { useSyncTrigger } from './useSyncTrigger';
import {
  buildClusterProgress,
  buildScanProgress,
  buildStatusText,
  derivePipelinePhase,
  deriveLatestJobId,
  getLatestJobByType,
  isScanRunning as getIsScanRunning,
  type PipelinePhase,
} from './jobStateMachineUtils';
import { useJobStateMachineEffects, type ProjectionSyncState } from './useJobStateMachineEffects';
import { useJobStateMachineMutations } from './useJobStateMachineMutations';
import { useJobPersistence } from './useJobPersistence';
import { useJobProgressStream } from './useJobProgressStream';
import { useCombinedScanStatus } from './useRecognitionHooks';

export type { JobPhase, PipelinePhase } from './jobStateMachineUtils';

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

  const { scanMutation, clusterMutation, cancelMutation } = useJobStateMachineMutations({
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
  const { scanStatusQuery, batchRunStatusQuery } = useCombinedScanStatus(jobId ?? null, activeJobIds, batchRunId);

  useEffect(() => {
    if (!jobId) {
      return;
    }
    const message = scanStatusQuery.error instanceof Error ? scanStatusQuery.error.message : '';
    if (message.includes('(404)')) {
      onJobNotFound?.(jobId);
    }
  }, [jobId, onJobNotFound, scanStatusQuery.error]);

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
    cluster: () => clusterMutation.mutate(),
    latestClusterJob,
    currentPhase,
    syncTrigger,
    projectionSyncState,
    projectionSyncNonce,
    setProjectionSyncState,
    setProjectionError,
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
        batchRunStatus: batchRunStatusQuery.data,
        latestJobId,
        scanPending: scanMutation.isPending,
      }),
    [
      activeJobIds,
      batchRunStatusQuery.data,
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
        currentPhase,
        activeJobIds,
        activeJobs,
        sseProgress,
        latestScanJob,
        batchRunStatus: batchRunStatusQuery.data,
        fallbackProgress: scanStatusQuery.data?.progress,
      }),
    [batchRunStatusQuery.data, currentPhase, activeJobIds, activeJobs, sseProgress, latestScanJob, scanStatusQuery.data?.progress],
  );

  const clusterProgress = useMemo(() => buildClusterProgress(currentPhase, sseProgress), [currentPhase, sseProgress]);

  const isScanRunning = useMemo(
    () =>
      getIsScanRunning({
        scanPending: scanMutation.isPending,
        waitingForCompletion: isWaitingForScanCompletion,
        activeJobIds,
        sseStatus,
        scanStatus: scanStatusQuery.data,
        batchRunStatus: batchRunStatusQuery.data,
      }),
    [activeJobIds, batchRunStatusQuery.data, isWaitingForScanCompletion, scanMutation.isPending, scanStatusQuery.data, sseStatus],
  );

  const scanStallSeconds = useMemo(() => {
    if (typeof stalledForSeconds !== 'number') {
      return null;
    }

    return currentPhase === 'idle' ? null : stalledForSeconds;
  }, [currentPhase, stalledForSeconds]);

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
    cluster: clusterMutation.mutate,
    retryProjectionSync,
    retryScanStream,
  };
};

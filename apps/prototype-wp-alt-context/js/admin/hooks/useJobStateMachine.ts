import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

  // The job the SSE transport is currently attached to. Mirrored on a ref so the cancel
  // handler below — which runs from a mutation callback, after the commit — can name it
  // without re-creating the mutation on every render.
  const streamJobIdRef = useRef<string | null>(null);
  // One slot, not a set: a cancel applies to the run that is streaming right now, and the next
  // scan clears it. A growing collection of cancelled ids would be an accumulator with no
  // purge (RES-07, lexicons/engineering.md:118).
  const [cancelledStreamJobId, setCancelledStreamJobId] = useState<string | null>(null);

  /**
   * Release the SSE transport when a cancel succeeds (FEBT2-LB-NEW-02, RES-20 at
   * lexicons/engineering.md:131).
   *
   * `clearActiveJobs()` alone is not enough. It nulls the stream id only on the path where
   * `latestJobId` comes from `latestScanJob`; when the backend has auto-chained a clustering
   * job, `deriveLatestJobId` falls back to `scanStatus.id` (jobStateMachineUtils.ts:74-78) and
   * the transport stays open on a run the operator stopped — frames for cancelled work, and a
   * connection held by a scope that never releases it.
   */
  const handleCancelComplete = useCallback(() => {
    setCancelledStreamJobId(streamJobIdRef.current);
    onCancelComplete?.();
  }, [onCancelComplete]);

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
    resolveScanRequestId,
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
    onCancelComplete: handleCancelComplete,
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

  useEffect(() => {
    streamJobIdRef.current = latestJobId;
  });

  // A cancelled run gets no transport, whichever derivation produced its id. Null is the
  // teardown signal the stream hook already honours (pinned in its own suite), so the release
  // path has one implementation rather than a second close() API on the hook.
  const streamJobId = latestJobId === cancelledStreamJobId ? null : latestJobId;

  // The scan-submit -> SSE correlation seam (FEBT2-LB-NEW-03). This hook is the only place
  // that sees both the submit unit and the stream, so it is the only place the join can be
  // made. The resolver answers `null` for a job no submit in this session created, so a
  // rehydrated or auto-chained clustering job mints its own id rather than inheriting one.
  const {
    progress: sseProgress,
    status: sseStatus,
    isOnline,
    etaSeconds,
    isPrimary,
    stalledForSeconds,
    retry: retryScanStream,
  } = useJobProgressStream(streamJobId, { resolveRequestId: resolveScanRequestId });
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
      // A new run reclaims the cancel latch; leaving it set would suppress the stream for a
      // job id the backend legitimately re-issued.
      setCancelledStreamJobId(null);
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

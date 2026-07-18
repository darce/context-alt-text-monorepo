import { useEffect, useMemo, useRef } from 'react';
import type { QueryClient, UseMutationResult } from '@tanstack/react-query';

import { getConfig } from '../api/config';
import { queryKeys } from '../api/queryKeys';
import type { SyncTriggerResponse } from '../api/recognition';
import type { BatchRunStatus, JobStatusResponse } from '../api/recognition/types/scan';
import { runAfterCooldown } from '../utils/recognitionCooldown';
import { isScanSuccessStatus, type PipelinePhase } from './jobStateMachineUtils';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';

export type ProjectionSyncState = 'idle' | 'syncing' | 'ready' | 'acknowledging' | 'error';

/**
 * E15-23: projection-ready must force visible findings data to refresh, not
 * merely invalidate broad caches. Targets every findings queue the Workbench
 * renders plus the current page's active media-identity queries
 * (refetchQueries on the `media.identities()` prefix only re-runs mounted
 * queries, so the active `identitiesByIds(mediaIds)` page refetches without
 * threading media ids through this boundary).
 */
const refetchFindingsQueries = (queryClient: QueryClient): Promise<unknown> => {
  let tenantId = '';
  try {
    tenantId = getConfig().tenant_id ?? '';
  } catch {
    tenantId = '';
  }

  const refetches = [
    queryClient.refetchQueries({ queryKey: queryKeys.suggestions.pending() }),
    queryClient.refetchQueries({ queryKey: queryKeys.suggestions.mergePending() }),
    queryClient.refetchQueries({ queryKey: queryKeys.suggestions.namePending() }),
    queryClient.refetchQueries({ queryKey: queryKeys.media.identities() }),
  ];
  if (tenantId !== '') {
    refetches.push(queryClient.refetchQueries({ queryKey: queryKeys.clusters.topUnlabeled(tenantId) }));
  }

  return Promise.allSettled(refetches);
};

interface JobStateMachineEffectsOptions {
  scanStatus: JobStatusResponse | undefined;
  batchRunStatus: BatchRunStatus | undefined;
  queryClient: QueryClient;
  activeJobs: PersistedJob[];
  isWaitingForScanCompletion: boolean;
  setIsWaitingForScanCompletion: (value: boolean) => void;
  sseStatus: JobStatus;
  removeJob: (id: string) => void;
  cluster: () => void;
  latestClusterJob: PersistedJob | null;
  currentPhase: PipelinePhase;
  syncTrigger: UseMutationResult<SyncTriggerResponse, Error, void, unknown>;
  projectionSyncState: ProjectionSyncState;
  projectionSyncNonce: number;
  setProjectionSyncState: (value: ProjectionSyncState) => void;
  setProjectionError: (value: string | null) => void;
}

export const useJobStateMachineEffects = ({
  scanStatus,
  batchRunStatus,
  queryClient,
  activeJobs,
  isWaitingForScanCompletion,
  setIsWaitingForScanCompletion,
  sseStatus,
  removeJob,
  cluster,
  latestClusterJob,
  currentPhase,
  syncTrigger,
  projectionSyncState,
  projectionSyncNonce,
  setProjectionSyncState,
  setProjectionError,
}: JobStateMachineEffectsOptions) => {
  const backendHandledClustering = scanStatus?.type === 'clustering' || scanStatus?.progress?.phase === 'clustering';
  const lastProjectionAttemptRef = useRef<string | null>(null);
  const syncProjectionRef = useRef(syncTrigger.mutateAsync);
  const projectionSnapshotVersion = useMemo(
    () => (typeof scanStatus?.snapshot_version === 'number' ? scanStatus.snapshot_version : null),
    [scanStatus?.snapshot_version],
  );
  const projectionJobId = useMemo(() => {
    if (typeof scanStatus?.source_job_id === 'string' && scanStatus.source_job_id.length > 0) {
      return scanStatus.source_job_id;
    }

    return latestClusterJob?.id ?? null;
  }, [latestClusterJob?.id, scanStatus?.source_job_id]);
  const projectionTarget = useMemo(() => {
    if (
      (currentPhase !== 'projecting' && projectionSyncState !== 'error') ||
      !projectionJobId ||
      projectionSnapshotVersion === null
    ) {
      return null;
    }

    return {
      jobId: projectionJobId,
      snapshotVersion: projectionSnapshotVersion,
      attemptKey: `${projectionJobId}:${projectionSnapshotVersion}:${projectionSyncNonce}`,
    };
  }, [currentPhase, projectionJobId, projectionSnapshotVersion, projectionSyncNonce, projectionSyncState]);

  useEffect(() => {
    syncProjectionRef.current = syncTrigger.mutateAsync;
  }, [syncTrigger.mutateAsync]);

  useEffect(() => {
    // BND-1: completed_with_errors is a terminal partial-success — refresh findings just like a
    // clean completion so a partially-failed scan still surfaces its results immediately.
    if (isScanSuccessStatus(scanStatus?.status)) {
      // Refetch burst bypasses refetchInterval — hold it out of an active 429 cooldown.
      runAfterCooldown(() => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
        void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.all });
      });
    }
  }, [scanStatus?.status, queryClient]);

  useEffect(() => {
    if (!isWaitingForScanCompletion || !batchRunStatus?.terminal_state) {
      return;
    }

    setIsWaitingForScanCompletion(false);
    activeJobs.filter((job) => job.type === 'scan').forEach((job) => removeJob(job.id));
    runAfterCooldown(() => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    });
    if (!backendHandledClustering && batchRunStatus.failed_total === 0 && batchRunStatus.accepted_total > 0) {
      cluster();
    }
  }, [
    batchRunStatus,
    backendHandledClustering,
    activeJobs,
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

    // BND-1 (SSE channel): completed_with_errors is terminal — clean up the cluster job + refresh,
    // else a partial-success clustering run leaves the UI stuck in the clustering phase.
    const clusteringCompleted = isScanSuccessStatus(sseStatus) || sseStatus === 'failed';
    if (clusteringCompleted && currentPhase === 'clustering') {
      removeJob(latestClusterJob.id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    }
  }, [sseStatus, currentPhase, latestClusterJob, queryClient, removeJob]);

  useEffect(() => {
    if (currentPhase !== 'projecting' && projectionSyncState !== 'error') {
      lastProjectionAttemptRef.current = null;
      setProjectionSyncState('idle');
      setProjectionError(null);
      return;
    }

    if (!projectionTarget || lastProjectionAttemptRef.current === projectionTarget.attemptKey) {
      return;
    }

    lastProjectionAttemptRef.current = projectionTarget.attemptKey;

    const executeProjectionSync = async () => {
      try {
        setProjectionError(null);
        setProjectionSyncState('syncing');

        const syncResult = await syncProjectionRef.current();
        if (!syncResult.synced) {
          throw new Error(syncResult.reason === 'sync_failed' ? 'Waiting for service…' : 'Syncing results failed.');
        }

        if (lastProjectionAttemptRef.current !== projectionTarget.attemptKey) {
          return;
        }

        setProjectionSyncState('ready');
        void refetchFindingsQueries(queryClient);
      } catch (error) {
        if (lastProjectionAttemptRef.current !== projectionTarget.attemptKey) {
          return;
        }

        setProjectionSyncState('error');
        setProjectionError(error instanceof Error ? error.message : 'Syncing results failed.');
      }
    };

    void executeProjectionSync();
  }, [
    currentPhase,
    projectionTarget,
    projectionSyncState,
    queryClient,
    setProjectionError,
    setProjectionSyncState,
    projectionSyncNonce,
  ]);
};

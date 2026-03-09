import { useEffect, useMemo, useRef } from 'react';
import type { QueryClient, UseMutationResult } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import type { SyncTriggerResponse } from '../api/recognition';
import type { JobStatusResponse } from '../api/recognition/types/scan';
import type { PipelinePhase } from './jobStateMachineUtils';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';

export type ProjectionSyncState = 'idle' | 'syncing' | 'acknowledging' | 'error';

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
  currentPhase: PipelinePhase;
  syncTrigger: UseMutationResult<SyncTriggerResponse, Error, void, unknown>;
  acknowledgeProjection: UseMutationResult<
    { status: string; snapshot_version: number },
    Error,
    { jobId: string; snapshotVersion: number },
    unknown
  >;
  projectionSyncNonce: number;
  setProjectionSyncState: (value: ProjectionSyncState) => void;
  setProjectionError: (value: string | null) => void;
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
  syncTrigger,
  acknowledgeProjection,
  projectionSyncNonce,
  setProjectionSyncState,
  setProjectionError,
}: JobStateMachineEffectsOptions) => {
  const backendHandledClustering = scanStatus?.type === 'clustering' || scanStatus?.progress?.phase === 'clustering';
  const lastProjectionAttemptRef = useRef<string | null>(null);
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
    if (currentPhase !== 'projecting' || !projectionJobId || projectionSnapshotVersion === null) {
      return null;
    }

    return {
      jobId: projectionJobId,
      snapshotVersion: projectionSnapshotVersion,
      attemptKey: `${projectionJobId}:${projectionSnapshotVersion}:${projectionSyncNonce}`,
    };
  }, [currentPhase, projectionJobId, projectionSnapshotVersion, projectionSyncNonce]);

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
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      if (!backendHandledClustering) {
        cluster();
      }
    }
  }, [
    backendHandledClustering,
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

  useEffect(() => {
    if (currentPhase !== 'projecting') {
      lastProjectionAttemptRef.current = null;
      setProjectionSyncState('idle');
      setProjectionError(null);
      return;
    }

    if (!projectionTarget || lastProjectionAttemptRef.current === projectionTarget.attemptKey) {
      return;
    }

    lastProjectionAttemptRef.current = projectionTarget.attemptKey;
    let cancelled = false;

    const runProjectionSync = async () => {
      try {
        setProjectionError(null);
        setProjectionSyncState('syncing');

        const syncResult = await syncTrigger.mutateAsync();
        if (!syncResult.synced) {
          throw new Error(syncResult.reason === 'sync_failed' ? 'Waiting for service…' : 'Syncing results failed.');
        }

        setProjectionSyncState('acknowledging');
        await acknowledgeProjection.mutateAsync({
          jobId: projectionTarget.jobId,
          snapshotVersion: projectionTarget.snapshotVersion,
        });

        if (cancelled) {
          return;
        }

        removeJob(projectionTarget.jobId);
        setProjectionSyncState('idle');
        void queryClient.invalidateQueries({ queryKey: queryKeys.jobs.status(projectionTarget.jobId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.sync.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      } catch (error) {
        if (cancelled) {
          return;
        }

        setProjectionSyncState('error');
        setProjectionError(error instanceof Error ? error.message : 'Syncing results failed.');
      }
    };

    void runProjectionSync();

    return () => {
      cancelled = true;
    };
  }, [
    acknowledgeProjection,
    currentPhase,
    projectionTarget,
    queryClient,
    removeJob,
    setProjectionError,
    setProjectionSyncState,
    syncTrigger,
  ]);
};

import React, { useMemo, useState, useEffect } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { useQueryClient } from '@tanstack/react-query';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import {
  useCancelScanJobs,
  useClusterIdentities,
  useScanIdentities,
  useCombinedScanStatus,
} from '../hooks/useRecognitionHooks';
import { useRecognitionJobHistory } from '../hooks/useRecognitionJobHistory';
import { useWorkbenchMedia } from '../hooks/useWorkbenchMedia';
import { useMediaSelectionState } from '../hooks/useMediaSelectionState';
import { useWorkbenchFilters } from '../hooks/useWorkbenchFilters';
import { useJobPersistence } from '../hooks/useJobPersistence';
import { useJobProgressStream } from '../hooks/useJobProgressStream';
import { MediaSelection } from './workbench/MediaSelection';
import { SuggestionReviewPanel } from './workbench/identity-clusters';
import { BatchPanel, ConfirmPanel, RecentJobsPanel, ScanActionPanel, rosterClustersUrl } from './workbench/Panels';

interface AltContextAdminConfig {
  nonce: string;
  endpoints: {
    workbenchMedia: string;
    recognitionAnalyze: string;
    recognitionJobs: string;
    recognitionCluster: string;
    recognitionClusters: string;
    recognitionClusterLabels: string;
    recognitionTrainingStage: string;
    recognitionMediaIdentities: string;
    recognitionReassignIdentity: string;
    recognitionIdentitySuggestions: string;
    recognitionSuggestions: string;
    recognitionRevertMerge: string;
    recognitionCreateClusterForIdentity: string;
  };
}

declare global {
  interface Window {
    AltContextAdmin?: AltContextAdminConfig;
    wpApiSettings?: {
      root: string;
      nonce: string;
    };
  }
}

const MEDIA_PAGE_SIZE = 10;
const TAB_IDS = {
  scan: 'scan',
  batch: 'batch',
  confirm: 'confirm',
} as const;
type WorkbenchTab = (typeof TAB_IDS)[keyof typeof TAB_IDS];

interface WorkbenchSection {
  id: WorkbenchTab;
  label: string;
  title: string;
  body: string;
}

const WORKBENCH_SECTIONS: WorkbenchSection[] = [
  {
    id: TAB_IDS.scan,
    label: __('Scan', 'alt-context'),
    title: __('Scan Media Queue', 'alt-context'),
    body: __(
      'Scan your library for images that still need descriptive metadata, filtering by status or search term.',
      'alt-context',
    ),
  },
  {
    id: TAB_IDS.batch,
    label: __('Batch', 'alt-context'),
    title: __('Batch Operations', 'alt-context'),
    body: __('Group the selected media, run recognition jobs, and prep face scans before publishing.', 'alt-context'),
  },
  {
    id: TAB_IDS.confirm,
    label: __('Confirm', 'alt-context'),
    title: __('Confirm & Publish', 'alt-context'),
    body: __('Compare before/after states, spot-check compliance, and push updates to WordPress media.', 'alt-context'),
  },
];

export const WorkbenchPage = (): React.JSX.Element => {
  const [activeSection, setActiveSection] = useState<WorkbenchTab>(TAB_IDS.scan);
  const [clusterMessage, setClusterMessage] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const { activeJobs, addJob, removeJob } = useJobPersistence();
  const activeJobIds = useMemo(() => activeJobs.map((j) => j.id), [activeJobs]);
  const [isWaitingForScanCompletion, setIsWaitingForScanCompletion] = useState(false);
  const [isCancellingScan, setIsCancellingScan] = useState(false);
  const queryClient = useQueryClient();

  const { jobId, jobHistory, jobStatuses, rememberJob, selectJob, clearHistory } = useRecognitionJobHistory();
  const { selection, selectedMedia, toggleRow, toggleAll, isPageFullySelected } = useMediaSelectionState();
  const { searchQuery, currentPage, setCurrentPage, handleSearchChange, normalizedSearch } = useWorkbenchFilters();

  const mediaQuery = useWorkbenchMedia({
    page: currentPage,
    perPage: MEDIA_PAGE_SIZE,
    search: normalizedSearch,
    enabled: activeSection === TAB_IDS.scan,
  });

  const mediaData = mediaQuery.data;
  const mediaItems = mediaQuery.itemsWithIdentities ?? mediaData?.items ?? [];
  const totalPages = mediaData?.totalPages ?? 1;
  const totalCount = mediaData?.total ?? 0;
  const hasIdentities = mediaItems.length > 0;
  const allPageRowsChecked = isPageFullySelected(mediaItems);
  const identityQuery = mediaQuery.identitiesQuery;

  const scanMutation = useScanIdentities({
    onMutate: () => {
      setScanError(null);
      activeJobIds.forEach((id) => removeJob(id));
      setIsWaitingForScanCompletion(false);
    },
    onSuccess: (data) => {
      const jobIds = data.map((job) => job.id).filter((id): id is string => Boolean(id));
      if (jobIds.length > 0) {
        rememberJob(jobIds[0]);
        const totalItems = data[0].progress?.total ?? 0;
        jobIds.forEach((id) => addJob(id, 'scan', totalItems));
      }
      setIsWaitingForScanCompletion(true);

      setClusterMessage(null);
      setActiveSection(TAB_IDS.confirm);
      void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : __('Recognition job failed. Please try again.', 'alt-context');
      setScanError(message);
    },
  });
  const clusterMutation = useClusterIdentities({
    onSuccess: (data) => {
      if (data.id && data.status === 'pending') {
        // This is an async job
        addJob(data.id, 'clustering', data.total_identities_clustered || 0);
        return;
      }
      setClusterMessage(
        sprintf(
          __('Created %d clusters for %d identities.', 'alt-context'),
          data.clusters_created,
          data.total_identities_clustered,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : __('Clustering failed. Please try again.', 'alt-context');
      setScanError(message);
    },
  });

  // Track jobs by type for proper phase derivation
  const latestScanJob = useMemo(() => {
    const scanJobs = activeJobs.filter((j) => j.type === 'scan');
    return scanJobs[scanJobs.length - 1] ?? null;
  }, [activeJobs]);
  const latestClusterJob = useMemo(() => {
    const clusterJobs = activeJobs.filter((j) => j.type === 'clustering');
    return clusterJobs[clusterJobs.length - 1] ?? null;
  }, [activeJobs]);

  // Derive current phase from which jobs exist (clustering takes precedence if both exist)
  const currentPhase = useMemo(() => {
    if (latestClusterJob) {
      return 'clustering' as const;
    }
    if (latestScanJob) {
      return 'scanning' as const;
    }
    return 'idle' as const;
  }, [latestScanJob, latestClusterJob]);

  // Use appropriate job for SSE based on current phase
  const latestJobId = useMemo(() => {
    return currentPhase === 'clustering' ? (latestClusterJob?.id ?? null) : (latestScanJob?.id ?? null);
  }, [currentPhase, latestScanJob, latestClusterJob]);
  const {
    progress: sseProgress,
    status: sseStatus,
    isOnline,
    etaSeconds,
    isPrimary,
  } = useJobProgressStream(latestJobId);

  const { scanStatusQuery } = useCombinedScanStatus(jobId, []); // Use for history polling, not active jobs

  const cancelMutation = useCancelScanJobs({
    onMutate: () => {
      setIsCancellingScan(true);
    },
    onSuccess: () => {
      setIsWaitingForScanCompletion(false);
      activeJobIds.forEach((id) => removeJob(id));
      void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    },
    onError: (error) => {
      const message =
        error instanceof Error
          ? error.message
          : __('Unable to cancel recognition job. Please try again.', 'alt-context');
      setScanError(message);
    },
    onSettled: () => {
      setIsCancellingScan(false);
    },
  });

  const scanStatusText = useMemo(() => {
    if (clusterMutation.isPending || sseStatus === 'clustering') {
      if (sseProgress && sseStatus === 'clustering') {
        return sprintf(__('Clustering %d/%d identities…', 'alt-context'), sseProgress.completed, sseProgress.total);
      }
      return __('Clustering faces…', 'alt-context');
    }

    if (activeJobIds.length > 0) {
      if (sseStatus === 'completed') {
        return 'completed';
      }
      if (sseStatus === 'failed') {
        return 'failed';
      }

      // Prefer message from query if it's the same job and has a message
      const latestQueryData = scanStatusQuery.data;
      if (latestQueryData?.id === latestJobId && latestQueryData.message) {
        return latestQueryData.message;
      }

      // For multi-job, the hook tracks the latest; we could aggregate if needed
      return sseStatus === 'pending' ? __('Starting scan…', 'alt-context') : __('Processing media…', 'alt-context');
    }
    const statusMessage = scanStatusQuery.data?.message;
    const statusValue = scanStatusQuery.data?.status;
    if (statusMessage && statusValue !== 'completed' && statusValue !== 'failed') {
      return statusMessage;
    }
    return statusValue ?? (scanMutation.isPending ? __('Starting scan…', 'alt-context') : undefined);
  }, [
    activeJobIds,
    sseStatus,
    scanStatusQuery.data,
    latestJobId,
    scanMutation.isPending,
    clusterMutation.isPending,
    sseProgress,
  ]);

  const scanProgress = useMemo(() => {
    if (activeJobIds.length === 0) {
      return scanStatusQuery.data?.progress ?? null;
    }

    // For batched scans, aggregate totalItems from all scan jobs
    const scanJobs = activeJobs.filter((j) => j.type === 'scan');
    if (scanJobs.length > 1 && sseProgress) {
      // Aggregate: total = sum of all job totals, completed = estimate based on jobs done
      const totalItems = scanJobs.reduce((sum, j) => sum + j.totalItems, 0);
      // Use SSE progress from current job, scale to overall
      const currentJobIndex = scanJobs.findIndex((j) => j.id === latestScanJob?.id);
      const completedJobs = currentJobIndex >= 0 ? currentJobIndex : 0;
      const completedFromPriorJobs = scanJobs.slice(0, completedJobs).reduce((sum, j) => sum + j.totalItems, 0);
      return {
        completed: completedFromPriorJobs + sseProgress.completed,
        total: totalItems,
      };
    }

    return sseProgress;
  }, [activeJobIds.length, activeJobs, sseProgress, latestScanJob, scanStatusQuery.data?.progress]);

  const isScanRunning = useMemo(() => {
    if (scanMutation.isPending || isWaitingForScanCompletion) {
      return true;
    }

    if (activeJobIds.length > 0) {
      return sseStatus === 'pending' || sseStatus === 'running';
    }

    const status = scanStatusQuery.data?.status;
    return status === 'pending' || status === 'running';
  }, [
    scanMutation.isPending,
    isWaitingForScanCompletion,
    activeJobIds.length,
    sseStatus,
    scanStatusQuery.data?.status,
  ]);

  useEffect(() => {
    if (scanStatusQuery.data?.status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    }
  }, [scanStatusQuery.data?.status, queryClient]);

  // Handle scan job completion → trigger clustering
  useEffect(() => {
    if (!isWaitingForScanCompletion || activeJobIds.length === 0) {
      return;
    }

    const completed = sseStatus === 'completed' || sseStatus === 'failed';

    if (completed && latestScanJob) {
      setIsWaitingForScanCompletion(false);
      // Remove ALL completed scan jobs (batched scans create multiple jobs)
      activeJobs.filter((j) => j.type === 'scan').forEach((j) => removeJob(j.id));
      // Trigger clustering
      clusterMutation.mutate();
      void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    }
  }, [
    sseStatus,
    activeJobIds,
    activeJobs,
    latestScanJob,
    isWaitingForScanCompletion,
    clusterMutation,
    queryClient,
    removeJob,
  ]);

  // Handle clustering job completion → remove from active jobs
  useEffect(() => {
    if (!latestClusterJob) {
      return;
    }

    const clusteringCompleted = sseStatus === 'completed' || sseStatus === 'failed';
    if (clusteringCompleted && currentPhase === 'clustering') {
      removeJob(latestClusterJob.id);
      void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
      void queryClient.invalidateQueries({ queryKey: ['recognition-clusters'] });
    }
  }, [sseStatus, currentPhase, latestClusterJob, queryClient, removeJob]);

  const statusMessage = useMemo(() => {
    if (mediaQuery.isFetching) {
      return __('Updating media queue…', 'alt-context');
    }

    if (mediaQuery.isError) {
      return __('Unable to load media. Please try again.', 'alt-context');
    }

    if (totalCount === 0) {
      return normalizedSearch
        ? sprintf(__('No media found for “%s”.', 'alt-context'), normalizedSearch)
        : __('No media items match the current filters.', 'alt-context');
    }

    return sprintf(_n('Showing %d media item.', 'Showing %d media items.', totalCount, 'alt-context'), totalCount);
  }, [mediaQuery.isError, mediaQuery.isFetching, normalizedSearch, totalCount]);

  const handleScanFaces = (): void => {
    const mediaIds = selectedMedia.map((item) => item.id);
    if (mediaIds.length === 0) {
      return;
    }

    scanMutation.mutate(mediaIds);
  };

  const handleCancelScan = (): void => {
    const targets = activeJobIds.length > 0 ? activeJobIds : jobId ? [jobId] : [];
    if (targets.length === 0) {
      return;
    }
    cancelMutation.mutate(targets);
  };

  const handleSelectJobFromHistory = (id: string): void => {
    selectJob(id);
    setActiveSection(TAB_IDS.confirm);
  };

  const handleClusterFaces = (): void => {
    clusterMutation.mutate();
  };

  const scanSection = WORKBENCH_SECTIONS[0];
  const batchSection = WORKBENCH_SECTIONS[1];
  const confirmSection = WORKBENCH_SECTIONS[2];

  return (
    <section className="acx-workbench" aria-labelledby="acx-workbench-title">
      <Tabs
        value={activeSection}
        onValueChange={(value) => setActiveSection(value as WorkbenchTab)}
        className="acx-workbench__tabs"
      >
        <TabsList className="acx-workbench__tabs-list" aria-label={__('Workbench steps', 'alt-context')}>
          {WORKBENCH_SECTIONS.map((section) => (
            <TabsTrigger
              key={section.id}
              value={section.id}
              className="acx-workbench__tabs-trigger"
              aria-label={section.title}
            >
              {section.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="acx-workbench__panels">
          {!isOnline && (
            <div className="acx-notice acx-notice--warning">
              {__('Network connection lost. Reconnecting…', 'alt-context')}
            </div>
          )}
          {!isPrimary && !!latestJobId && (
            <div className="acx-notice acx-notice--info">
              {__('This job is being processed in another tab.', 'alt-context')}
            </div>
          )}
          <TabsContent
            value={TAB_IDS.scan}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-scan"
          >
            <h2 id="acx-workbench-section-scan">{scanSection.title}</h2>
            <p>{scanSection.body}</p>

            <ScanActionPanel
              selectedCount={selectedMedia.length}
              onScanFaces={handleScanFaces}
              onCancelScan={handleCancelScan}
              isScanning={isScanRunning}
              isCancelling={isCancellingScan}
              statusText={scanStatusText}
              jobId={latestJobId ?? jobId}
              errorMessage={scanError}
              progress={scanProgress}
              etaSeconds={etaSeconds}
              isSynced={!isPrimary && !!latestJobId}
            />
            {!isScanRunning && !hasIdentities && !scanMutation.isPending && <NoMediaPanel />}
            <SuggestionReviewPanel />
            <MediaSelection
              items={mediaItems}
              isLoading={mediaQuery.isFetching}
              isError={mediaQuery.isError}
              onRetry={mediaQuery.isError ? () => void mediaQuery.refetch() : undefined}
              statusMessage={statusMessage}
              searchQuery={searchQuery}
              onSearchChange={handleSearchChange}
              selection={selection}
              onToggleRow={toggleRow}
              onToggleAll={(checked) => toggleAll(mediaItems, checked)}
              currentPage={currentPage}
              totalPages={totalPages}
              onPageChange={setCurrentPage}
              areAllPageRowsChecked={allPageRowsChecked}
              identityQuery={identityQuery}
            />
          </TabsContent>

          <TabsContent
            value={TAB_IDS.batch}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-batch"
          >
            <h2 id="acx-workbench-section-batch">{batchSection.title}</h2>
            <p>{batchSection.body}</p>
            <BatchPanel items={selectedMedia} />
            <RecentJobsPanel
              jobs={jobHistory}
              statuses={jobStatuses}
              activeJobId={jobId}
              onSelect={handleSelectJobFromHistory}
              onClear={clearHistory}
            />
          </TabsContent>

          <TabsContent
            value={TAB_IDS.confirm}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-confirm"
          >
            <h2 id="acx-workbench-section-confirm">{confirmSection.title}</h2>
            <p>{confirmSection.body}</p>
            <ConfirmPanel
              jobId={jobId}
              status={scanStatusText}
              onCluster={handleClusterFaces}
              isClustering={
                clusterMutation.isPending ||
                (activeJobIds.length > 0 && (sseStatus === 'pending' || sseStatus === 'running'))
              }
              clusterMessage={clusterMessage}
              onViewClusters={() => window.location.assign(rosterClustersUrl())}
              progress={scanProgress}
              etaSeconds={etaSeconds}
              isSynced={!isPrimary && !!latestJobId}
            />
            <RecentJobsPanel
              jobs={jobHistory}
              statuses={jobStatuses}
              activeJobId={jobId}
              onSelect={handleSelectJobFromHistory}
              onClear={clearHistory}
            />
          </TabsContent>
        </div>
      </Tabs>
    </section>
  );
};

const NoMediaPanel = () => (
  <div className="acx-apply-panel acx-apply-panel--empty">
    <p>{__('No media items to analyze. Check your filters or upload more images.', 'alt-context')}</p>
  </div>
);

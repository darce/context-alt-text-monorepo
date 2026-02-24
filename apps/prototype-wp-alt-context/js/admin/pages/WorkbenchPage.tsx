import React, { useEffect, useMemo, useState } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { useJobStateMachine } from '../hooks/useJobStateMachine';
import { useRecognitionJobHistory } from '../hooks/useRecognitionJobHistory';
import { useWorkbenchMedia } from '../hooks/useWorkbenchMedia';
import { useMediaSelectionState } from '../hooks/useMediaSelectionState';
import { useWorkbenchFilters } from '../hooks/useWorkbenchFilters';
import { getConfig } from '../api/config';
import { MediaSelection } from './workbench/MediaSelection';
import { ClusterLabelingPanel, ClusterReviewPanel, SuggestionReviewPanel } from './workbench/identity-clusters';
import { SyncStatusIndicator } from './workbench/SyncStatusIndicator';
import { BatchPanel, ConfirmPanel, RecentJobsPanel, ScanActionPanel, rosterClustersUrl } from './workbench/Panels';
import { ErrorBoundary } from '../../components/ErrorBoundary';

const MEDIA_PAGE_SIZE_OPTIONS = [10, 50, 100] as const;
const DEFAULT_MEDIA_PAGE_SIZE = MEDIA_PAGE_SIZE_OPTIONS[0];
const MEDIA_PAGE_SIZE_STORAGE_KEY = 'acx-media-page-size';

const getStoredMediaPageSize = (): number => {
  if (typeof window === 'undefined') {
    return DEFAULT_MEDIA_PAGE_SIZE;
  }

  try {
    const stored = window.localStorage.getItem(MEDIA_PAGE_SIZE_STORAGE_KEY);
    if (!stored) {
      return DEFAULT_MEDIA_PAGE_SIZE;
    }
    const parsed = Number.parseInt(stored, 10);
    return MEDIA_PAGE_SIZE_OPTIONS.includes(parsed as (typeof MEDIA_PAGE_SIZE_OPTIONS)[number])
      ? parsed
      : DEFAULT_MEDIA_PAGE_SIZE;
  } catch {
    return DEFAULT_MEDIA_PAGE_SIZE;
  }
};
const TAB_IDS = {
  scan: 'scan',
  batch: 'batch',
  confirm: 'confirm',
} as const;
type WorkbenchTab = (typeof TAB_IDS)[keyof typeof TAB_IDS];

type ClusterPanelMode = 'none' | 'label' | 'review';

interface ClusterPanelState {
  mode: ClusterPanelMode;
  clusterId: string | null;
}

type ClusterPanelAction =
  | { type: 'open_label'; clusterId: string }
  | { type: 'open_review'; clusterId: string }
  | { type: 'close' };

const clusterPanelReducer = (state: ClusterPanelState, action: ClusterPanelAction): ClusterPanelState => {
  switch (action.type) {
    case 'open_label':
      return { mode: 'label', clusterId: action.clusterId };
    case 'open_review':
      return { mode: 'review', clusterId: action.clusterId };
    case 'close':
      return { mode: 'none', clusterId: null };
    default:
      return state;
  }
};

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
  const [perPage, setPerPage] = useState<number>(() => getStoredMediaPageSize());
  const [knownTotalPages, setKnownTotalPages] = useState<number | null>(null);
  const { recognitionUrlFallback } = getConfig();
  const [clusterPanel, dispatchClusterPanel] = React.useReducer(clusterPanelReducer, {
    mode: 'none',
    clusterId: null,
  });

  const { jobId, jobHistory, jobStatuses, rememberJob, selectJob, clearHistory } = useRecognitionJobHistory();
  const { selection, selectedMedia, toggleRow, toggleAll, isPageFullySelected } = useMediaSelectionState();
  const {
    searchQuery,
    currentPage,
    setCurrentPage,
    handleSearchChange,
    normalizedSearch,
    statusFilter,
    handleStatusChange,
  } = useWorkbenchFilters();
  const clampedPage = Math.min(Math.max(1, currentPage), knownTotalPages ?? currentPage);

  const mediaQuery = useWorkbenchMedia({
    page: clampedPage,
    perPage,
    search: normalizedSearch,
    status: statusFilter,
    enabled: activeSection === TAB_IDS.scan,
  });

  const mediaData = mediaQuery.data;
  const mediaItems = mediaQuery.itemsWithIdentities ?? mediaData?.items ?? [];
  const totalPages = mediaData?.totalPages ?? 1;
  const totalCount = mediaData?.total ?? 0;
  const hasIdentities = mediaItems.length > 0;
  const allPageRowsChecked = isPageFullySelected(mediaItems);
  const identityQuery = mediaQuery.identitiesQuery;

  useEffect(() => {
    if (currentPage === clampedPage) {
      return;
    }
    setCurrentPage(clampedPage);
  }, [clampedPage, currentPage, setCurrentPage]);

  useEffect(() => {
    if (!mediaData) {
      return;
    }
    setKnownTotalPages(mediaData.totalPages);
  }, [mediaData]);

  const {
    isScanRunning,
    isCancellingScan,
    statusText,
    scanProgress,
    etaSeconds,
    isOnline,
    isPrimary,
    latestJobId,
    activeJobIds,
    scan,
    cancelScan: performCancel,
    cluster: performCluster,
  } = useJobStateMachine({
    jobId,
    onScanStart: () => {
      setScanError(null);
    },
    onScanComplete: (jobIds) => {
      if (jobIds.length > 0) {
        rememberJob(jobIds[0]);
      }
      setClusterMessage(null);
    },
    onScanError: (message) => {
      setScanError(message);
    },
    onClusterComplete: (data) => {
      setClusterMessage(
        sprintf(
          __('Created %d clusters for %d identities.', 'alt-context'),
          data.clusters_created,
          data.total_identities_clustered,
        ),
      );
    },
    onClusterError: (message) => {
      setScanError(message);
    },
  });

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

    scan(mediaIds);
  };

  const handleCancelScan = (): void => {
    const targets = activeJobIds.length > 0 ? activeJobIds : jobId ? [jobId] : [];
    if (targets.length === 0) {
      return;
    }
    performCancel(targets);
  };

  const handleSelectJobFromHistory = (id: string): void => {
    selectJob(id);
    setActiveSection(TAB_IDS.confirm);
  };

  const handleClusterFaces = (): void => {
    performCluster();
  };

  const handlePerPageChange = (nextPerPage: number): void => {
    if (!MEDIA_PAGE_SIZE_OPTIONS.includes(nextPerPage as (typeof MEDIA_PAGE_SIZE_OPTIONS)[number])) {
      return;
    }
    setPerPage(nextPerPage);
    setCurrentPage(1);
  };

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    try {
      window.localStorage.setItem(MEDIA_PAGE_SIZE_STORAGE_KEY, String(perPage));
    } catch {
      // Ignore storage failures (private mode, quota, etc.).
    }
  }, [perPage]);

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
          {recognitionUrlFallback && (
            <div className="acx-notice acx-notice--warning">
              {__(
                'Alt Context is using the local recognition URL fallback (http://localhost:8000). Configure acx_recognition_url or ACX_RECOGNITION_URL for this environment.',
                'alt-context',
              )}
            </div>
          )}
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
              statusText={statusText}
              jobId={latestJobId ?? jobId}
              errorMessage={scanError}
              progress={scanProgress}
              etaSeconds={etaSeconds}
              isSynced={!isPrimary && !!latestJobId}
            />
            <SyncStatusIndicator />
            {!isScanRunning && !hasIdentities && <NoMediaPanel />}
            <ErrorBoundary>
              {clusterPanel.mode === 'review' && clusterPanel.clusterId ? (
                <ClusterReviewPanel
                  clusterId={clusterPanel.clusterId}
                  onClose={() => dispatchClusterPanel({ type: 'close' })}
                />
              ) : clusterPanel.mode === 'label' && clusterPanel.clusterId ? (
                <ClusterLabelingPanel
                  clusterId={clusterPanel.clusterId}
                  onClose={() => dispatchClusterPanel({ type: 'close' })}
                  onLabel={() => {
                    dispatchClusterPanel({ type: 'close' });
                  }}
                />
              ) : (
                <SuggestionReviewPanel
                  onLabel={(clusterId) => dispatchClusterPanel({ type: 'open_label', clusterId })}
                  onReview={(clusterId) => dispatchClusterPanel({ type: 'open_review', clusterId })}
                />
              )}
            </ErrorBoundary>
            <MediaSelection
              items={mediaItems}
              isLoading={mediaQuery.isPending && mediaItems.length === 0}
              isError={mediaQuery.isError}
              onRetry={mediaQuery.isError ? () => void mediaQuery.refetch() : undefined}
              statusMessage={statusMessage}
              searchQuery={searchQuery}
              onSearchChange={handleSearchChange}
              statusFilter={statusFilter}
              onStatusFilterChange={handleStatusChange}
              selection={selection}
              onToggleRow={toggleRow}
              onToggleAll={(checked) => toggleAll(mediaItems, checked)}
              currentPage={clampedPage}
              totalPages={totalPages}
              perPage={perPage}
              onPerPageChange={handlePerPageChange}
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
              status={statusText}
              onCluster={handleClusterFaces}
              isClustering={
                isScanRunning // Simplified, logic is in hook
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

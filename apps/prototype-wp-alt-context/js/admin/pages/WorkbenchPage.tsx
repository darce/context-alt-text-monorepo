import React, { useMemo, useState, useEffect } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { useQueryClient } from '@tanstack/react-query';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { useClusterIdentities, useScanIdentities, useScanStatus } from '../hooks/useRecognitionHooks';
import { useRecognitionJobHistory } from '../hooks/useRecognitionJobHistory';
import { useWorkbenchMedia } from '../hooks/useWorkbenchMedia';
import { useMediaSelectionState } from '../hooks/useMediaSelectionState';
import { useWorkbenchFilters } from '../hooks/useWorkbenchFilters';
import { MediaSelection } from './workbench/MediaSelection';
import { BatchPanel, ConfirmPanel, RecentJobsPanel, ScanActionPanel, rosterClustersUrl } from './workbench/Panels';

type AltContextAdminConfig = {
  nonce: string;
  endpoints: {
    workbenchMedia: string;
    workbenchRecognitionAnalyze?: string;
    workbenchRecognitionJobs?: string;
    workbenchRecognitionCluster?: string;
    workbenchRecognitionClusters?: string;
    workbenchFaceScan?: string;
    workbenchFaceClusters?: string;
    recognitionAnalyze: string;
    recognitionJobs: string;
    recognitionCluster: string;
    recognitionClusters: string;
  };
};

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

type WorkbenchSection = {
  id: WorkbenchTab;
  label: string;
  title: string;
  body: string;
};

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
  const allPageRowsChecked = isPageFullySelected(mediaItems);
  const identityQuery = mediaQuery.identitiesQuery;

  const scanMutation = useScanIdentities({
    onMutate: () => {
      setScanError(null);
    },
    onSuccess: (data) => {
      rememberJob(data.job_id);
      setClusterMessage(null);
      setActiveSection(TAB_IDS.confirm);
      queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : __('Recognition job failed. Please try again.', 'alt-context');
      setScanError(message);
    },
  });
  const clusterMutation = useClusterIdentities({
    onSuccess: (data) => {
      setClusterMessage(
        sprintf(
          __('Created %d clusters for %d identities.', 'alt-context'),
          data.clusters_created,
          data.total_identities_clustered,
        ),
      );
    },
  });
  const scanStatusQuery = useScanStatus(jobId, Boolean(jobId));
  const scanStatusText =
    scanStatusQuery.data?.status ?? (scanMutation.isPending ? __('Starting scan…', 'alt-context') : undefined);

  useEffect(() => {
    if (scanStatusQuery.data?.status === 'completed') {
      queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    }
  }, [scanStatusQuery.data?.status, queryClient]);

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
              isScanning={scanMutation.isPending}
              statusText={scanStatusText}
              jobId={jobId}
              errorMessage={scanError}
            />
        <MediaSelection
          items={mediaItems}
          isLoading={mediaQuery.isFetching}
          isError={mediaQuery.isError}
          onRetry={mediaQuery.isError ? () => mediaQuery.refetch() : undefined}
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
              isClustering={clusterMutation.isPending}
              clusterMessage={clusterMessage}
              onViewClusters={() => window.location.assign(rosterClustersUrl())}
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

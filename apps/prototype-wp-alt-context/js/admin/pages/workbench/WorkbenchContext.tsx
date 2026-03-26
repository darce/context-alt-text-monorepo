import React, { createContext, useContext, useMemo, useReducer, useEffect, useState } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { useRecognitionJobHistory } from '../../hooks/useRecognitionJobHistory';
import { useMediaSelectionState } from '../../hooks/useMediaSelectionState';
import { useWorkbenchFilters } from '../../hooks/useWorkbenchFilters';
import { useJobStateMachine } from '../../hooks/useJobStateMachine';
import { useWorkbenchMedia, type WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import { getConfig } from '../../api/config';
import { useTabParam } from '../../hooks/useTabParam';
import { useOverlayParam } from '../../hooks/useOverlayParam';
import type { JobProgress } from '../../api/recognition/types/scan';
import type { ClusterResponse, WorkbenchOverlay } from '../../api/recognition';
import type { WorkbenchMediaStatus } from '../../api/workbenchMediaApi';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';

export const TAB_IDS = {
  scan: 'scan',
  confirm: 'confirm',
} as const;

export type WorkbenchTab = (typeof TAB_IDS)[keyof typeof TAB_IDS];
export type { WorkbenchOverlay } from '../../api/recognition';

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

interface WorkbenchContextValue {
  // Navigation
  activeSection: WorkbenchTab;
  setActiveSection: (section: WorkbenchTab) => void;
  activeOverlay: WorkbenchOverlay;
  setActiveOverlay: (overlay: WorkbenchOverlay) => void;

  // Job History
  jobId: string | undefined | null;
  jobHistory: string[];
  jobStatuses: Record<string, string>;
  rememberJob: (id: string) => void;
  selectJob: (id: string) => void;
  forgetJob: (id: string) => void;
  clearHistory: () => void;

  // Selection
  selection: Record<string, boolean>;
  selectedMedia: WorkbenchMediaItem[];
  toggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
  toggleAll: (items: WorkbenchMediaItem[], checked: boolean) => void;
  isPageFullySelected: (items: WorkbenchMediaItem[]) => boolean;

  // Filters & Media Queue
  searchQuery: string;
  currentPage: number;
  perPage: number;
  handleSearchChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  statusFilter: WorkbenchMediaStatus;
  handleStatusChange: (status: WorkbenchMediaStatus) => void;
  setCurrentPage: (page: number) => void;
  setPerPage: (perPage: number) => void;
  mediaQuery: ReturnType<typeof useWorkbenchMedia>;
  statusMessage: string;

  // State Machine
  isScanRunning: boolean;
  isCancellingScan: boolean;
  currentPhase: PipelinePhase;
  projectionSyncState: ProjectionSyncState;
  projectionError: string | null;
  statusText: string | undefined;
  scanProgress: JobProgress | null;
  clusterProgress: JobProgress | null;
  etaSeconds: number | null;
  isOnline: boolean;
  isPrimary: boolean;
  latestJobId: string | undefined | null;
  scan: (mediaIds: number[]) => void;
  cancelScan: (jobIds: string[]) => void;
  cluster: () => void;
  retryProjectionSync: () => void;
  activeJobIds: string[];
  handleSelectJobFromHistory: (id: string) => void;

  // Cluster Panels
  clusterPanel: ClusterPanelState;
  dispatchClusterPanel: React.Dispatch<ClusterPanelAction>;
  clusterMessage: string | null;
  setClusterMessage: (msg: string | null) => void;
  scanError: string | null;
  setScanError: (msg: string | null) => void;
  hasIdentities: boolean;

  // Config/Env
  recognitionUrlFallback: boolean;
}

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export const WorkbenchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeSection, setActiveSection] = useTabParam<WorkbenchTab>('tab', TAB_IDS.scan, [
    TAB_IDS.scan,
    TAB_IDS.confirm,
  ]);
  const [activeOverlay, setActiveOverlay] = useOverlayParam<Exclude<WorkbenchOverlay, null>>('panel', [
    'conflicts',
    'dead-letter',
  ]);
  const [clusterMessage, setClusterMessage] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [knownTotalPages, setKnownTotalPages] = useState<number | null>(null);
  const { recognitionUrlFallback } = getConfig();
  const [clusterPanel, dispatchClusterPanel] = useReducer(clusterPanelReducer, {
    mode: 'none',
    clusterId: null,
  });

  const { jobId, jobHistory, jobStatuses, rememberJob, selectJob, forgetJob, clearHistory } =
    useRecognitionJobHistory();
  const { selection, selectedMedia, toggleRow, toggleAll, isPageFullySelected } = useMediaSelectionState();
  const {
    searchQuery,
    currentPage,
    perPage,
    setPerPage,
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
  const totalCount = mediaData?.total ?? 0;

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
    currentPhase,
    projectionSyncState,
    projectionError,
    statusText,
    scanProgress,
    clusterProgress,
    etaSeconds,
    isOnline,
    isPrimary,
    latestJobId,
    activeJobIds,
    scan,
    cancelScan,
    cluster,
    retryProjectionSync,
  } = useJobStateMachine({
    jobId,
    onJobNotFound: (staleJobId: string) => {
      forgetJob(staleJobId);
    },
    onScanStart: () => {
      setScanError(null);
    },
    onScanComplete: (jobIds: string[]) => {
      if (jobIds.length > 0) {
        rememberJob(jobIds[0]);
      }
      setClusterMessage(null);
    },
    onScanError: (message: string) => {
      setScanError(message);
    },
    onClusterComplete: (data: ClusterResponse) => {
      setClusterMessage(
        sprintf(
          __('Created %d clusters for %d identities.', 'alt-context'),
          data.clusters_created,
          data.total_identities_clustered,
        ),
      );
    },
    onClusterError: (message: string) => {
      setScanError(message);
    },
  });

  const handleSelectJobFromHistory = React.useCallback(
    (id: string): void => {
      selectJob(id);
      setActiveSection(TAB_IDS.confirm);
    },
    [selectJob, setActiveSection],
  );

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

  const value = useMemo(
    () => ({
      activeSection,
      setActiveSection,
      activeOverlay,
      setActiveOverlay,
      jobId,
      jobHistory,
      jobStatuses,
      rememberJob,
      selectJob,
      forgetJob,
      clearHistory,
      selection,
      selectedMedia,
      toggleRow,
      toggleAll,
      isPageFullySelected,
      searchQuery,
      currentPage: clampedPage,
      perPage,
      handleSearchChange,
      statusFilter,
      handleStatusChange,
      setCurrentPage,
      setPerPage,
      mediaQuery,
      statusMessage,
      isScanRunning,
      isCancellingScan,
      currentPhase,
      projectionSyncState,
      projectionError,
      statusText,
      scanProgress,
      clusterProgress,
      etaSeconds,
      isOnline,
      isPrimary,
      latestJobId,
      scan,
      cancelScan,
      cluster,
      retryProjectionSync,
      activeJobIds,
      handleSelectJobFromHistory,
      clusterPanel,
      dispatchClusterPanel,
      clusterMessage,
      setClusterMessage,
      scanError,
      setScanError,
      hasIdentities: mediaItems.length > 0,
      recognitionUrlFallback: !!recognitionUrlFallback,
    }),
    [
      activeSection,
      activeOverlay,
      setActiveSection,
      setActiveOverlay,
      jobId,
      jobHistory,
      jobStatuses,
      rememberJob,
      selectJob,
      forgetJob,
      clearHistory,
      selection,
      selectedMedia,
      toggleRow,
      toggleAll,
      isPageFullySelected,
      searchQuery,
      clampedPage,
      perPage,
      handleSearchChange,
      statusFilter,
      handleStatusChange,
      setCurrentPage,
      mediaQuery,
      statusMessage,
      isScanRunning,
      isCancellingScan,
      currentPhase,
      projectionSyncState,
      projectionError,
      statusText,
      scanProgress,
      clusterProgress,
      etaSeconds,
      isOnline,
      isPrimary,
      latestJobId,
      scan,
      cancelScan,
      cluster,
      retryProjectionSync,
      activeJobIds,
      handleSelectJobFromHistory,
      clusterPanel,
      clusterMessage,
      scanError,
      mediaItems.length,
      recognitionUrlFallback,
      setPerPage,
    ],
  );

  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
};

export const useWorkbenchContext = () => {
  const context = useContext(WorkbenchContext);
  if (!context) {
    throw new Error('useWorkbenchContext must be used within a WorkbenchProvider');
  }
  return context;
};

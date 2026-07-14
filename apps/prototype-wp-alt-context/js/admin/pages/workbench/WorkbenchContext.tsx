import React, { createContext, useContext, useMemo, useReducer, useEffect, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useRecognitionJobHistory } from '../../hooks/useRecognitionJobHistory';
import { useJobStateMachine } from '../../hooks/useJobStateMachine';
import { getConfig } from '../../api/config';
import { useSearchParams } from 'react-router-dom';
import { useTabParam } from '../../hooks/useTabParam';
import { useOverlayParam } from '../../hooks/useOverlayParam';
import { WorkbenchMediaProvider } from './WorkbenchMediaContext';
import type { BatchRunStatus, JobProgress } from '../../api/recognition/types/scan';
import type { ClusterResponse, WorkbenchOverlay } from '../../api/recognition';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';
import type { RecognitionHistorySource } from '../../hooks/recognitionJobHistoryUtils';

export const TAB_IDS = {
  scan: 'scan',
} as const;

/** Legacy deep-link value only — URL shim maps it to scan + advanced open. */
export const LEGACY_CONFIRM_TAB = 'confirm';

export type WorkbenchTab = (typeof TAB_IDS)[keyof typeof TAB_IDS];
export type { WorkbenchOverlay } from '../../api/recognition';

export const ADVANCED_PARAM = 'advanced';
export const ADVANCED_OPEN_VALUE = 'open';

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
  isAdvancedOpen: boolean;
  setAdvancedOpen: (open: boolean) => void;

  // Job History
  jobId: string | undefined | null;
  jobHistory: string[];
  jobStatuses: Record<string, string>;
  historySource: RecognitionHistorySource;
  rememberJob: (id: string) => void;
  selectJob: (id: string) => void;
  forgetJob: (id: string) => void;
  clearHistory: () => void;

  // State Machine
  isScanRunning: boolean;
  isCancellingScan: boolean;
  currentPhase: PipelinePhase;
  projectionSyncState: ProjectionSyncState;
  projectionError: string | null;
  statusText: string | undefined;
  scanProgress: JobProgress | null;
  clusterProgress: JobProgress | null;
  batchRunStatus: BatchRunStatus | null;
  scanStallSeconds: number | null;
  etaSeconds: number | null;
  isOnline: boolean;
  isPrimary: boolean;
  latestJobId: string | undefined | null;
  scan: (mediaIds: number[]) => void;
  cancelScan: (jobIds: string[]) => void;
  cluster: () => void;
  retryProjectionSync: () => void;
  retryScanStream: () => void;
  activeJobIds: string[];
  handleSelectJobFromHistory: (id: string) => void;

  // Cluster Panels
  clusterPanel: ClusterPanelState;
  dispatchClusterPanel: React.Dispatch<ClusterPanelAction>;
  clusterMessage: string | null;
  setClusterMessage: (msg: string | null) => void;
  scanError: string | null;
  setScanError: (msg: string | null) => void;

  // Config/Env
  recognitionSource: 'service' | 'local';
  effectiveTargetUrl: string;
}

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export const WorkbenchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeSection, setActiveSection] = useTabParam<WorkbenchTab>('tab', TAB_IDS.scan, [TAB_IDS.scan]);
  const [activeOverlay, setActiveOverlay] = useOverlayParam<Exclude<WorkbenchOverlay, null>>('panel', [
    'conflicts',
    'dead-letter',
  ]);
  const [clusterMessage, setClusterMessage] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const { recognitionSource, effectiveTargetUrl } = getConfig();
  const [clusterPanel, dispatchClusterPanel] = useReducer(clusterPanelReducer, {
    mode: 'none',
    clusterId: null,
  });

  // shim owned by E21-10 — maps legacy ?tab=confirm to scan + advanced drawer open
  useEffect(() => {
    if (searchParams.get('tab') !== LEGACY_CONFIRM_TAB) {
      return;
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', TAB_IDS.scan);
        next.set(ADVANCED_PARAM, ADVANCED_OPEN_VALUE);
        return next;
      },
      { replace: true },
    );
  }, [searchParams, setSearchParams]);

  const isAdvancedOpen = searchParams.get(ADVANCED_PARAM) === ADVANCED_OPEN_VALUE;

  const setAdvancedOpen = React.useCallback(
    (open: boolean): void => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (open) {
            next.set(ADVANCED_PARAM, ADVANCED_OPEN_VALUE);
          } else {
            next.delete(ADVANCED_PARAM);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const {
    jobId,
    jobHistory,
    jobStatuses,
    historySource = 'unavailable',
    rememberJob,
    selectJob,
    forgetJob,
    clearHistory,
  } = useRecognitionJobHistory();

  const {
    isScanRunning,
    isCancellingScan,
    currentPhase,
    projectionSyncState,
    projectionError,
    statusText,
    scanProgress,
    clusterProgress,
    batchRunStatus,
    scanStallSeconds,
    etaSeconds,
    isOnline,
    isPrimary,
    latestJobId,
    activeJobIds,
    scan,
    cancelScan,
    cluster,
    retryProjectionSync,
    retryScanStream,
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
      setAdvancedOpen(true);
    },
    [selectJob, setAdvancedOpen],
  );

  const value = useMemo<WorkbenchContextValue>(
    () => ({
      activeSection,
      setActiveSection,
      activeOverlay,
      setActiveOverlay,
      isAdvancedOpen,
      setAdvancedOpen,
      jobId,
      jobHistory,
      jobStatuses,
      historySource,
      rememberJob,
      selectJob,
      forgetJob,
      clearHistory,
      isScanRunning,
      isCancellingScan,
      currentPhase,
      projectionSyncState,
      projectionError,
      statusText,
      scanProgress,
      clusterProgress,
      batchRunStatus,
      scanStallSeconds,
      etaSeconds,
      isOnline,
      isPrimary,
      latestJobId,
      scan,
      cancelScan,
      cluster,
      retryProjectionSync,
      retryScanStream,
      activeJobIds,
      handleSelectJobFromHistory,
      clusterPanel,
      dispatchClusterPanel,
      clusterMessage,
      setClusterMessage,
      scanError,
      setScanError,
      recognitionSource,
      effectiveTargetUrl,
    }),
    [
      activeSection,
      activeOverlay,
      setActiveSection,
      setActiveOverlay,
      isAdvancedOpen,
      setAdvancedOpen,
      jobId,
      jobHistory,
      jobStatuses,
      historySource,
      rememberJob,
      selectJob,
      forgetJob,
      clearHistory,
      isScanRunning,
      isCancellingScan,
      currentPhase,
      projectionSyncState,
      projectionError,
      statusText,
      scanProgress,
      clusterProgress,
      batchRunStatus,
      scanStallSeconds,
      etaSeconds,
      isOnline,
      isPrimary,
      latestJobId,
      scan,
      cancelScan,
      cluster,
      retryProjectionSync,
      retryScanStream,
      activeJobIds,
      handleSelectJobFromHistory,
      clusterPanel,
      clusterMessage,
      scanError,
      recognitionSource,
      effectiveTargetUrl,
    ],
  );

  return (
    <WorkbenchContext.Provider value={value}>
      <WorkbenchMediaProvider>{children}</WorkbenchMediaProvider>
    </WorkbenchContext.Provider>
  );
};

export const useWorkbenchContext = (): WorkbenchContextValue => {
  const context = useContext(WorkbenchContext);
  if (!context) {
    throw new Error('useWorkbenchContext must be used within a WorkbenchProvider');
  }
  return context;
};

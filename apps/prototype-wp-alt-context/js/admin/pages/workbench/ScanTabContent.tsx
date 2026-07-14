import React from 'react';
import { __ } from '@wordpress/i18n';
import { ErrorBoundary } from '../../../components/ErrorBoundary';
import { useScrollRestoration } from '../../hooks/useScrollRestoration';
import { ScanActionPanel } from './Panels';
import { JobTimeline } from './JobTimeline';
import {
  ClusterLabelingPanel,
  ClusterReviewPanel,
  SuggestionReviewPanel,
  WorkbenchFindingsPanel,
} from './identity-clusters';
import { useWorkbenchFindings } from './identity-clusters/useWorkbenchFindings';
import { MediaSelection } from './MediaSelection';
import { useWorkbenchContext } from './WorkbenchContext';
import { useWorkbenchMediaContext } from './WorkbenchMediaContext';

const ScanScrollRestoration = () => {
  useScrollRestoration('workbench-scan');
  return null;
};

const NoMediaPanel = () => (
  <div className="acx-apply-panel acx-apply-panel--empty">
    <h3>{__('Your analysis queue is empty', 'alt-context')}</h3>
    <p>
      {__(
        'Search for specific media items below or adjust your filters to find images that need analysis. Once you select items, they will appear here ready to be scanned.',
        'alt-context',
      )}
    </p>
  </div>
);

export const ScanTabContent = (): React.JSX.Element => {
  const {
    isScanRunning,
    isCancellingScan,
    statusText,
    jobId,
    scanError,
    scanProgress,
    clusterProgress,
    batchRunStatus,
    scanStallSeconds,
    currentPhase,
    projectionSyncState,
    etaSeconds,
    isPrimary,
    latestJobId,
    clusterPanel,
    dispatchClusterPanel,
    cancelScan,
    retryScanStream,
    activeJobIds,
  } = useWorkbenchContext();
  const { hasIdentities } = useWorkbenchMediaContext().mediaQueue;

  const findingsDetailRef = React.useRef<HTMLDivElement>(null);
  const findings = useWorkbenchFindings();
  const [userExpandedMedia, setUserExpandedMedia] = React.useState(false);
  const previousHasFindings = React.useRef(findings.hasFindings);

  React.useEffect(() => {
    if (findings.hasFindings && !previousHasFindings.current) {
      setUserExpandedMedia(false);
    }
    previousHasFindings.current = findings.hasFindings;
  }, [findings.hasFindings]);

  const isMediaCollapsed =
    findings.hasFindings &&
    !userExpandedMedia &&
    !findings.isLoading &&
    !findings.isError &&
    !findings.isUnavailable;

  const handleTargetFindings = (): void => {
    const anchor = findingsDetailRef.current;
    if (!anchor) {
      return;
    }
    anchor.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    // WHY: move keyboard/SR focus with the scroll so "Review next" lands users on the queues.
    anchor.focus({ preventScroll: true });
  };

  const handleCancelScan = (): void => {
    const targets = activeJobIds.length > 0 ? activeJobIds : jobId ? [jobId] : [];
    if (targets.length === 0) {
      return;
    }
    cancelScan(targets);
  };

  return (
    <>
      <ScanActionPanel
        onCancelScan={handleCancelScan}
        isScanning={isScanRunning}
        isCancelling={isCancellingScan}
        statusText={statusText}
        jobId={latestJobId ?? jobId}
        errorMessage={scanError}
        progress={
          (currentPhase === 'clustering' || currentPhase === 'projecting') && clusterProgress
            ? clusterProgress
            : scanProgress
        }
        batchRunStatus={batchRunStatus}
        stallSeconds={scanStallSeconds}
        onRetryStream={retryScanStream}
        etaSeconds={etaSeconds}
        isSynced={!isPrimary && !!latestJobId}
      />
      <JobTimeline
        scanProgress={scanProgress}
        clusterProgress={clusterProgress}
        phase={currentPhase}
        projectionSyncState={projectionSyncState}
      />
      <ErrorBoundary>
        <WorkbenchFindingsPanel
          onLabel={(clusterId: string) => dispatchClusterPanel({ type: 'open_label', clusterId })}
          onTargetFindings={handleTargetFindings}
        />
      </ErrorBoundary>
      <ScanScrollRestoration />
      {!isScanRunning && !hasIdentities && <NoMediaPanel />}
      <ErrorBoundary>
        <div ref={findingsDetailRef} className="acx-findings-detail-anchor" tabIndex={-1}>
          {clusterPanel.mode === 'label' && clusterPanel.clusterId ? (
            <ClusterLabelingPanel
              clusterId={clusterPanel.clusterId}
              onClose={() => dispatchClusterPanel({ type: 'close' })}
              onLabel={() => {
                dispatchClusterPanel({ type: 'close' });
              }}
            />
          ) : clusterPanel.mode === 'review' && clusterPanel.clusterId ? (
            <ClusterReviewPanel
              clusterId={clusterPanel.clusterId}
              onClose={() => dispatchClusterPanel({ type: 'close' })}
            />
          ) : (
            <SuggestionReviewPanel
              onLabel={(clusterId: string) => dispatchClusterPanel({ type: 'open_label', clusterId })}
              onReview={(clusterId: string) => dispatchClusterPanel({ type: 'open_review', clusterId })}
            />
          )}
        </div>
      </ErrorBoundary>
      <MediaSelection collapsed={isMediaCollapsed} onExpand={() => setUserExpandedMedia(true)} />
    </>
  );
};

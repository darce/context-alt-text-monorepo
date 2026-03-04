import React from 'react';
import { __ } from '@wordpress/i18n';
import { ErrorBoundary } from '../../../components/ErrorBoundary';
import { useScrollRestoration } from '../../hooks/useScrollRestoration';
import { ScanActionPanel } from './Panels';
import { ClusterLabelingPanel, ClusterReviewPanel, SuggestionReviewPanel } from './identity-clusters';
import { MediaSelection } from './MediaSelection';
import { useWorkbenchContext } from './WorkbenchContext';


const ScanScrollRestoration = () => {
  useScrollRestoration('workbench-scan');
  return null;
};

const NoMediaPanel = () => (
  <div className="acx-apply-panel acx-apply-panel--empty">
    <h3>{__('Your analysis queue is empty', 'alt-context')}</h3>
    <p>
      {__('Search for specific media items below or adjust your filters to find images that need analysis. Once you select items, they will appear here ready to be scanned.', 'alt-context')}
    </p>
  </div>
);


export const ScanTabContent = (): React.JSX.Element => {
  const {
    selectedMedia,
    isScanRunning,
    isCancellingScan,
    statusText,
    jobId,
    scanError,
    scanProgress,
    etaSeconds,
    isPrimary,
    latestJobId,
    hasIdentities,
    clusterPanel,
    dispatchClusterPanel,
    scan,
    cancelScan,
    activeJobIds,

  } = useWorkbenchContext();

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
    cancelScan(targets);
  };

  return (

    <>
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
      <ScanScrollRestoration />
      {!isScanRunning && !hasIdentities && <NoMediaPanel />}
      <ErrorBoundary>
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
      </ErrorBoundary>
      <MediaSelection />
    </>
  );
};

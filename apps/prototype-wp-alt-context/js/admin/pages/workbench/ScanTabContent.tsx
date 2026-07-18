import React from 'react';
import { __ } from '@wordpress/i18n';
import { ErrorBoundary } from '../../../components/ErrorBoundary';
import {
  useWorkbenchFilters,
  type ReviewQueueBandParam,
  type ReviewQueueKindParam,
} from '../../hooks/useWorkbenchFilters';
import { useScrollRestoration } from '../../hooks/useScrollRestoration';
import { ScanActionPanel } from './Panels';
import { JobTimeline } from './JobTimeline';
import {
  ClusterLabelingPanel,
  ClusterReviewPanel,
  ReviewQueue,
  WorkbenchFindingsPanel,
  type ReviewQueueHandle,
} from './identity-clusters';
import { useWorkbenchFindings } from './identity-clusters/useWorkbenchFindings';
import { MediaSelection } from './MediaSelection';
import { useJobPipeline } from './JobPipelineContext';
import { useClusterPanel } from './ClusterPanelContext';
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
  const { scanRun, status, history, cancelScan, retryScanStream } = useJobPipeline();
  const { clusterPanel, dispatchClusterPanel } = useClusterPanel();
  const { hasIdentities } = useWorkbenchMediaContext().mediaQueue;
  const { queueState, setQueueState } = useWorkbenchFilters();

  const findingsDetailRef = React.useRef<HTMLDivElement>(null);
  const reviewQueueRef = React.useRef<ReviewQueueHandle>(null);
  // Open-target lifecycle announce (§11 / A11Y-21). Owned here so it survives
  // the review panel's rebind remount and retirement unmount.
  const [reviewLifecycleMessage, setReviewLifecycleMessage] = React.useState<string | null>(null);
  const findings = useWorkbenchFindings();
  const [userExpandedMedia, setUserExpandedMedia] = React.useState(false);
  const previousHasFindings = React.useRef(findings.hasFindings);

  // Lifted queue index + kind + band — survives label/review panel unmount of ReviewQueue.
  const [queueIndex, setQueueIndex] = React.useState(queueState.index);
  const [queueKind, setQueueKind] = React.useState<ReviewQueueKindParam>(queueState.kind);
  const [queueBand, setQueueBand] = React.useState<ReviewQueueBandParam>(queueState.band);
  // PR-31: id-keyed selection lifted beside index — panel round-trips preserve it.
  const [selectedSuggestionIds, setSelectedSuggestionIds] = React.useState<Set<string>>(
    () => new Set(),
  );

  // URL → local (reload / external writer).
  React.useEffect(() => {
    setQueueIndex(queueState.index);
    setQueueKind(queueState.kind);
    setQueueBand(queueState.band);
  }, [queueState.index, queueState.kind, queueState.band]);

  React.useEffect(() => {
    if (findings.hasFindings && !previousHasFindings.current) {
      setUserExpandedMedia(false);
    }
    previousHasFindings.current = findings.hasFindings;
  }, [findings.hasFindings]);

  const isMediaCollapsed =
    findings.hasFindings && !userExpandedMedia && !findings.isLoading && !findings.isError && !findings.isUnavailable;

  const handleIndexChange = React.useCallback(
    (nextIndex: number): void => {
      setQueueIndex(nextIndex);
      setQueueState({ index: nextIndex });
    },
    [setQueueState],
  );

  const handleKindChange = React.useCallback(
    (nextKind: ReviewQueueKindParam): void => {
      setQueueKind(nextKind);
      setQueueState({ kind: nextKind, index: 0 });
      setQueueIndex(0);
    },
    [setQueueState],
  );

  const handleBandChange = React.useCallback(
    (nextBand: ReviewQueueBandParam): void => {
      setQueueBand(nextBand);
      setQueueState({ band: nextBand, index: 0 });
      setQueueIndex(0);
    },
    [setQueueState],
  );

  const handleTargetFindings = (): void => {
    const anchor = findingsDetailRef.current;
    if (anchor) {
      anchor.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    }
    // Drive the mounted queue (not scroll-only): focus current card primary.
    if (reviewQueueRef.current) {
      reviewQueueRef.current.focusCurrentCard();
      return;
    }
    // Panel mode or empty: fall back to anchor focus.
    anchor?.focus({ preventScroll: true });
  };

  const handleCancelScan = (): void => {
    const targets = history.activeJobIds.length > 0 ? history.activeJobIds : history.jobId ? [history.jobId] : [];
    if (targets.length === 0) {
      return;
    }
    cancelScan(targets);
  };

  return (
    <>
      <ScanActionPanel scanRun={scanRun} onCancelScan={handleCancelScan} onRetryStream={retryScanStream} />
      <JobTimeline
        scanProgress={status.scanProgress}
        clusterProgress={status.clusterProgress}
        phase={status.currentPhase}
        projectionSyncState={status.projectionSyncState}
      />
      <ErrorBoundary>
        <WorkbenchFindingsPanel
          onLabel={(clusterId: string) => dispatchClusterPanel({ type: 'open_label', clusterId })}
          onTargetFindings={handleTargetFindings}
        />
      </ErrorBoundary>
      <ScanScrollRestoration />
      {!scanRun.isScanning && !hasIdentities && <NoMediaPanel />}
      <ErrorBoundary>
        <p className="acx-review-lifecycle-announce" role="status" aria-live="polite">
          {reviewLifecycleMessage}
        </p>
        <div ref={findingsDetailRef} className="acx-findings-detail-anchor" tabIndex={-1}>
          {clusterPanel.mode === 'label' && clusterPanel.clusterId ? (
            <ClusterLabelingPanel
              key={clusterPanel.clusterId}
              clusterId={clusterPanel.clusterId}
              onClose={() => dispatchClusterPanel({ type: 'close' })}
              onLabel={() => {
                dispatchClusterPanel({ type: 'close' });
              }}
            />
          ) : clusterPanel.mode === 'review' && clusterPanel.clusterId ? (
            <ClusterReviewPanel
              key={clusterPanel.clusterId}
              clusterId={clusterPanel.clusterId}
              onClose={() => dispatchClusterPanel({ type: 'close' })}
              onLifecycleAnnounce={setReviewLifecycleMessage}
              onFocusQueueRoot={() => {
                findingsDetailRef.current?.focus({ preventScroll: true });
              }}
            />
          ) : (
            <ReviewQueue
              ref={reviewQueueRef}
              index={queueIndex}
              onIndexChange={handleIndexChange}
              kind={queueKind}
              onKindChange={handleKindChange}
              band={queueBand}
              onBandChange={handleBandChange}
              selectedIds={selectedSuggestionIds}
              onSelectedIdsChange={setSelectedSuggestionIds}
              emptyStateAnchorRef={findingsDetailRef}
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

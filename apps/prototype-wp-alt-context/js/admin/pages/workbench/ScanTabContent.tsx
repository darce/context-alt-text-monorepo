import React from 'react';
import { __ } from '@wordpress/i18n';
import { ErrorBoundary } from '../../../components/ErrorBoundary';
import {
  QUEUE_ACTION,
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
import { useAriaAnnounce } from './identity-clusters/useAriaAnnounce';
import { useOpenReviewTargetLifecycle } from './identity-clusters/useOpenReviewTargetLifecycle';
import { useJobPipeline } from './JobPipelineContext';
import { useClusterPanel } from './ClusterPanelContext';
import { useWorkbenchMediaContext } from './WorkbenchMediaContext';
import { useReviewSurface } from './ReviewSurfaceContext';

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
  const { queueState, dispatchQueue } = useWorkbenchFilters();

  const findingsDetailRef = React.useRef<HTMLDivElement>(null);
  const reviewQueueRef = React.useRef<ReviewQueueHandle>(null);
  // Open-target lifecycle announce (§11 / A11Y-21). Owned here so it survives
  // the review panel's rebind remount and retirement unmount. BR-68: seq-keyed so
  // two consecutive identical closes both re-announce.
  const {
    message: reviewLifecycleMessage,
    seq: reviewLifecycleSeq,
    announce: announceReviewLifecycle,
  } = useAriaAnnounce();

  const focusQueueRoot = React.useCallback((): void => {
    const restore = (): void => {
      const trigger = findingsDetailRef.current?.querySelector<HTMLElement>('[data-acx-review-trigger]');
      if (trigger) {
        trigger.focus({ preventScroll: true });
        return;
      }
      findingsDetailRef.current?.focus({ preventScroll: true });
    };
    if (findingsDetailRef.current?.querySelector('[data-acx-review-trigger]')) {
      restore();
      return;
    }
    queueMicrotask(restore);
  }, []);

  // Open-target retirement lifecycle (§11 / FBT-1 ⑤). Owned here (always mounted)
  // so the rebind/close transition resolves render-phase against the live target
  // and survives the review panel's remount/unmount. `reviewClusterId` is the
  // cluster the review panel is actually mounted on (rebound survivor after a
  // merge, or null once retired).
  const { reviewClusterId } = useOpenReviewTargetLifecycle({
    requestedClusterId: clusterPanel.mode === 'review' ? clusterPanel.clusterId : null,
    onAnnounce: announceReviewLifecycle,
    onFocusQueueRoot: focusQueueRoot,
    onRetireClose: () => dispatchClusterPanel({ type: 'close' }),
    // BR-66: after a merge rebind, advance the reducer to the survivor so the
    // panel reducer and the mounted review target agree.
    onRebindSync: (survivorId) => dispatchClusterPanel({ type: 'open_review', clusterId: survivorId }),
  });

  const lastAnnouncedReviewId = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (reviewClusterId !== null && lastAnnouncedReviewId.current !== reviewClusterId) {
      lastAnnouncedReviewId.current = reviewClusterId;
      announceReviewLifecycle(__('Reviewing faces — press Back to return to suggestions', 'alt-context'));
    }
    if (reviewClusterId === null) {
      lastAnnouncedReviewId.current = null;
    }
  }, [announceReviewLifecycle, reviewClusterId]);
  // §7 / BR-75/BR-82/BR-83: the queue reports whether IT owns the viewport's single accent
  // primary (its card marker or bulk-commit marker) via the shared ReviewSurfaceContext. The
  // READER — the media footer's CTA demotion — lives in the sibling library host
  // (WorkbenchPageContent); ScanTabContent is the SETTER side only (WBUX-5 S1c-2).
  const { setCardPrimaryPresent } = useReviewSurface();

  // UXW2-1: URL (`rq=`) is the single owner of queue kind/band/index (DATA-14,
  // REF-09 — derive, don't mirror). One user action → one dispatchQueue write;
  // kind/band/clear reset the index inside the reducer.
  // PR-31: id-keyed selection lifted beside index — panel round-trips preserve it.
  const [selectedSuggestionIds, setSelectedSuggestionIds] = React.useState<Set<string>>(
    () => new Set(),
  );

  const handleClampIndex = React.useCallback(
    (nextIndex: number): void => {
      dispatchQueue({ type: QUEUE_ACTION.CLAMP_INDEX, index: nextIndex });
    },
    [dispatchQueue],
  );

  const handleStepIndex = React.useCallback(
    (delta: number, length: number): void => {
      dispatchQueue({ type: QUEUE_ACTION.STEP_INDEX, delta, length });
    },
    [dispatchQueue],
  );

  const handleKindChange = React.useCallback(
    (nextKind: ReviewQueueKindParam): void => {
      dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: nextKind });
    },
    [dispatchQueue],
  );

  const handleBandChange = React.useCallback(
    (nextBand: ReviewQueueBandParam): void => {
      dispatchQueue({ type: QUEUE_ACTION.SET_BAND, band: nextBand });
    },
    [dispatchQueue],
  );

  const handleClearFilters = React.useCallback((): void => {
    dispatchQueue({ type: QUEUE_ACTION.CLEAR_FILTERS });
  }, [dispatchQueue]);

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

  // E21-18 S1 / L3R-03: strip while scanning OR projecting (projection can outlive isScanning).
  const isJobActive = Boolean(scanRun.isScanning) || status.currentPhase === 'projecting';

  return (
    <>
      {isJobActive ? (
        // L3R-01: strip is visual-only — no role="status". Job announcements live on the
        // demoted panel's phase-stable live region (buildCoarseJobAnnouncement), not statusText ticks.
        <div className="acx-active-job-strip" data-testid="active-job-strip">
          <ScanActionPanel
            variant="compact"
            scanRun={scanRun}
            currentPhase={status.currentPhase}
            onCancelScan={handleCancelScan}
            onRetryStream={retryScanStream}
          />
          <JobTimeline
            compact
            scanProgress={status.scanProgress}
            clusterProgress={status.clusterProgress}
            phase={status.currentPhase}
            projectionSyncState={status.projectionSyncState}
          />
        </div>
      ) : null}

      <ScanScrollRestoration />

      {/* (b) Review queue promoted to top — named region (L3R-04 / design B.1) */}
      <section className="acx-workbench-control-queue" aria-labelledby="acx-workbench-queue-heading">
        <ErrorBoundary>
          <p
            key={reviewLifecycleSeq}
            className="acx-review-lifecycle-announce"
            role="status"
            aria-live="polite"
          >
            {reviewLifecycleMessage}
          </p>
          {/* L3R-08: ReviewQueue owns #acx-workbench-queue-heading; label/review panels do not —
              supply a stable region heading so aria-labelledby never dangles. */}
          {clusterPanel.mode === 'label' && clusterPanel.clusterId ? (
            <h3 id="acx-workbench-queue-heading" className="screen-reader-text">
              {__('Name this person', 'alt-context')}
            </h3>
          ) : null}
          <div ref={findingsDetailRef} className="acx-findings-detail-anchor" tabIndex={-1}>
            {clusterPanel.mode === 'label' && clusterPanel.clusterId ? (
              <ClusterLabelingPanel
                key={clusterPanel.clusterId}
                clusterId={clusterPanel.clusterId}
                onClose={() => dispatchClusterPanel({ type: 'close' })}
                onLabel={() => {
                  dispatchClusterPanel({ type: 'close' });
                  announceReviewLifecycle(__('Name saved. Back to review suggestions.', 'alt-context'));
                  focusQueueRoot();
                }}
              />
            ) : reviewClusterId !== null ? (
              <ClusterReviewPanel
                key={reviewClusterId}
                clusterId={reviewClusterId}
                onClose={() => {
                  dispatchClusterPanel({ type: 'close' });
                  announceReviewLifecycle(
                    __('Returned to review suggestions', 'alt-context'),
                  );
                  focusQueueRoot();
                }}
              />
            ) : (
              <ReviewQueue
                ref={reviewQueueRef}
                index={queueState.index}
                onClampIndex={handleClampIndex}
                onStepIndex={handleStepIndex}
                kind={queueState.kind}
                onKindChange={handleKindChange}
                band={queueState.band}
                onBandChange={handleBandChange}
                onClearFilters={handleClearFilters}
                selectedIds={selectedSuggestionIds}
                onSelectedIdsChange={setSelectedSuggestionIds}
                emptyStateAnchorRef={findingsDetailRef}
                onLabel={(clusterId: string) => dispatchClusterPanel({ type: 'open_label', clusterId })}
                onReview={(clusterId: string) => dispatchClusterPanel({ type: 'open_review', clusterId })}
                onCardPrimaryPresenceChange={setCardPrimaryPresent}
              />
            )}
          </div>
        </ErrorBoundary>
      </section>

      {/* (c) Findings demoted below the queue — named region (L3R-04 / design B.1) */}
      <section className="acx-workbench-control-findings" aria-labelledby="acx-workbench-findings-heading">
        <ErrorBoundary>
          <WorkbenchFindingsPanel onTargetFindings={handleTargetFindings} />
        </ErrorBoundary>
      </section>

      {!scanRun.isScanning && !hasIdentities && <NoMediaPanel />}

      {/* (d) Scan CTA + full timeline demoted to bottom; reachable from zero state (rg-003) */}
      <section className="acx-workbench-control-scan" aria-labelledby="acx-workbench-scan-heading">
        <h3 id="acx-workbench-scan-heading" className="acx-workbench-control-scan__title">
          {__('Scan', 'alt-context')}
        </h3>
        {/* L3R-02: while strip owns progress/cancel/timeline, demoted panel keeps unique detail only. */}
        <ScanActionPanel
          scanRun={scanRun}
          onCancelScan={handleCancelScan}
          onRetryStream={retryScanStream}
          suppressPrimaryChrome={isJobActive}
        />
        {!isJobActive ? (
          <JobTimeline
            scanProgress={status.scanProgress}
            clusterProgress={status.clusterProgress}
            phase={status.currentPhase}
            projectionSyncState={status.projectionSyncState}
          />
        ) : null}
      </section>
    </>
  );
};

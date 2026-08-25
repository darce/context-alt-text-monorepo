import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { StepMap, STEP_MAP_VALUES, type StepMapValue } from '../components/ui/StepMap';
import { SyncStatusIndicator } from './workbench/SyncStatusIndicator';
import { ScanTabContent } from './workbench/ScanTabContent';
import { MediaSelection } from './workbench/MediaSelection';
import { WorkbenchTwoPaneLayout } from './workbench/WorkbenchTwoPaneLayout';
import { AdvancedDrawer } from './workbench/AdvancedDrawer';
import { ConflictInbox } from './workbench/ConflictInbox';
import { DeadLetterPanel } from './workbench/DeadLetterPanel';
import { WorkbenchProvider } from './workbench/WorkbenchContext';
import { useWorkbenchNav } from './workbench/WorkbenchNavContext';
import { useClusterPanel } from './workbench/ClusterPanelContext';
import { useJobPipeline } from './workbench/JobPipelineContext';
import { useWorkbenchMediaContext } from './workbench/WorkbenchMediaContext';
import { useReviewSurface } from './workbench/ReviewSurfaceContext';
import { deriveReviewSurfaceActive } from './workbench/mediaFooterCtaState';
import { usePanesParam } from '../hooks/usePanesParam';
import { APP_LINK_VALUES } from '../navigation/appLinks';
import { deriveFaceGroupScatterState, FaceGroupScatter } from './workbench/FaceGroupScatter';

/**
 * The three-step Scan/Confirm/Review loop (NAV-09). Not a URL-owned tab id —
 * a display vocabulary for the step map, derived from state that already has
 * a single owner: `isAdvancedOpen` (WorkbenchNavContext) and `clusterPanel.mode`
 * (ClusterPanelContext). No new nav state is introduced.
 */
export const WORKBENCH_STEP_IDS = STEP_MAP_VALUES;
export type WorkbenchStepId = StepMapValue;

/**
 * Single derivation point for "which step am I on" (NAV-09). Priority:
 * an open cluster review target outranks the advanced drawer, which
 * outranks the scan default — both signals already exist and are owned
 * elsewhere (WorkbenchNavContext / ClusterPanelContext); this just reads them.
 */
export const deriveActiveWorkbenchStep = (input: {
  isAdvancedOpen: boolean;
  isReviewingCluster: boolean;
}): WorkbenchStepId => {
  if (input.isReviewingCluster) {
    return WORKBENCH_STEP_IDS.review;
  }
  if (input.isAdvancedOpen) {
    return WORKBENCH_STEP_IDS.confirm;
  }
  return WORKBENCH_STEP_IDS.scan;
};

export interface WorkbenchStepMapProps {
  activeStep: WorkbenchStepId;
  onSelectScan: () => void;
  onSelectConfirm: () => void;
}

/**
 * Ordered step map for the Scan/Confirm/Review loop [NAV-09]. Scan and Confirm
 * stay reachable (they mirror existing entry points: closing the advanced
 * drawer, opening it); Review has no free-standing entry point in the current
 * UI (it always needs a clusterId from the queue), so its list item is
 * informational only — this does not remove any existing reachability, and
 * does not gate a control behind a non-zero selection [rg-003].
 */
export const WorkbenchStepMap = ({
  activeStep,
  onSelectScan,
  onSelectConfirm,
}: WorkbenchStepMapProps): React.JSX.Element => (
  <StepMap
    activeStep={activeStep}
    steps={[
      { id: WORKBENCH_STEP_IDS.scan, label: __('Scan', 'alt-context'), onSelect: onSelectScan },
      { id: WORKBENCH_STEP_IDS.confirm, label: __('Confirm', 'alt-context'), onSelect: onSelectConfirm },
      { id: WORKBENCH_STEP_IDS.review, label: __('Review', 'alt-context') },
    ]}
  />
);

export const WorkbenchPage = (): React.JSX.Element => (
  <WorkbenchProvider>
    <WorkbenchPageContent />
  </WorkbenchProvider>
);

const WorkbenchPageContent = (): React.JSX.Element => {
  const {
    activeSection,
    recognitionSource,
    effectiveTargetUrl,
    activeOverlay,
    setActiveOverlay,
    isAdvancedOpen,
    setAdvancedOpen,
  } = useWorkbenchNav();
  const { clusterPanel, dispatchClusterPanel } = useClusterPanel();
  const { scanRun, status, retryProjectionSync } = useJobPipeline();
  const { detailTruncationNotice } = useWorkbenchMediaContext().mediaQueue;
  const [panes, setPanes] = usePanesParam();

  const activeWorkbenchStep = deriveActiveWorkbenchStep({
    isAdvancedOpen,
    isReviewingCluster: clusterPanel.mode === 'review',
  });

  const handleSelectScanStep = React.useCallback((): void => {
    setAdvancedOpen(false);
    if (clusterPanel.mode === 'review') {
      dispatchClusterPanel({ type: 'close' });
    }
  }, [setAdvancedOpen, clusterPanel.mode, dispatchClusterPanel]);

  const handleSelectConfirmStep = React.useCallback((): void => {
    setAdvancedOpen(true);
  }, [setAdvancedOpen]);

  // Review-surface footer signal rehomes here with MediaSelection (WBUX-5 S1c-2): the queue
  // setter (left control host) and the media reader (right library host) live in sibling
  // subtrees, bridged by ReviewSurfaceContext.
  const { cardPrimaryPresent } = useReviewSurface();

  // §7 media-footer CTA hierarchy (BR-83): the footer steps its CTAs down exactly when the
  // QUEUE owns the viewport's single accent primary. Collapse-aware: a collapsed control pane
  // renders the queue's card marker `hidden`, so the footer reclaims its accent (WBUX-5 S1c-2).
  const reviewSurfaceActive = deriveReviewSurfaceActive({
    cardPrimaryPresent,
    controlCollapsed: panes === APP_LINK_VALUES.panesControlCollapsed,
  });

  return (
    <section className="acx-workbench" aria-labelledby="acx-workbench-title">
      <h1 id="acx-workbench-title" className="acx-dashboard__title">
        {__('Review Queue', 'alt-context')}
      </h1>
      <div className="acx-workbench__panels">
        <SyncStatusIndicator
          activeSection={activeSection}
          pipelinePhase={status.currentPhase}
          projectionState={status.projectionSyncState}
          projectionError={status.projectionError}
          onRetryProjection={retryProjectionSync}
        />
        {activeOverlay ? (
          <section className="acx-workbench__overlay" aria-label={__('Review Queue overlay', 'alt-context')}>
            <div className="acx-workbench__overlay-header">
              <h2 className="acx-workbench__overlay-title">
                {activeOverlay === 'conflicts'
                  ? __('Conflict Inbox', 'alt-context')
                  : __('Failed Sync Queue', 'alt-context')}
              </h2>
              <button type="button" className="button button-link" onClick={() => setActiveOverlay(null)}>
                {__('Close', 'alt-context')}
              </button>
            </div>
            {activeOverlay === 'conflicts' ? <ConflictInbox /> : <DeadLetterPanel />}
          </section>
        ) : null}
        {recognitionSource === 'local' && (
          <div className="acx-notice acx-notice--info">
            <p>
              {sprintf(
                /* translators: %s is the effective local recognition service URL. */
                __(
                  'Alt Context is targeting the local recognition service at %s via the developer hatch.',
                  'alt-context',
                ),
                effectiveTargetUrl,
              )}
            </p>
            <p>
              {__(
                'Remove the ACX_RECOGNITION_SOURCE developer constant to use the hosted recognition service.',
                'alt-context',
              )}
            </p>
          </div>
        )}
        {!status.isOnline && (
          <div className="acx-notice acx-notice--warning">
            {__('Network connection lost. Reconnecting…', 'alt-context')}
          </div>
        )}
        {scanRun.isSynced && (
          <div className="acx-notice acx-notice--info">
            {__('This job is being processed in another tab.', 'alt-context')}
          </div>
        )}

        <WorkbenchStepMap
          activeStep={activeWorkbenchStep}
          onSelectScan={handleSelectScanStep}
          onSelectConfirm={handleSelectConfirmStep}
        />

        <WorkbenchTwoPaneLayout
          panes={panes}
          onPanesChange={setPanes}
          control={
            <div className="acx-workbench__panel">
              <h2>{__('Scan Media Queue', 'alt-context')}</h2>
              <p>
                {__(
                  'Scan your library for images that still need descriptive metadata, filtering by status or search term.',
                  'alt-context',
                )}
              </p>
              <FaceGroupScatter
                state={deriveFaceGroupScatterState({
                  isOnline: status.isOnline,
                  projectionSyncState: status.projectionSyncState,
                  isSynced: Boolean(scanRun.isSynced),
                  currentPhase: status.currentPhase,
                  clustersCreated:
                    scanRun.progress?.clusters_created ??
                    status.clusterProgress?.clusters_created ??
                    status.scanProgress?.clusters_created,
                })}
                onRetry={retryProjectionSync}
              />
              <ScanTabContent />
            </div>
          }
          library={
            <>
              {detailTruncationNotice && <div className="acx-notice acx-notice--info">{detailTruncationNotice}</div>}
              <MediaSelection reviewActive={reviewSurfaceActive} />
            </>
          }
        />

        <AdvancedDrawer />
      </div>
    </section>
  );
};

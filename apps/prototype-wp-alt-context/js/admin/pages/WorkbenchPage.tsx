import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

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

/**
 * The three-step Scan/Confirm/Review loop (NAV-09). Not a URL-owned tab id —
 * a display vocabulary for the step map, derived from state that already has
 * a single owner: `isAdvancedOpen` (WorkbenchNavContext) and `clusterPanel.mode`
 * (ClusterPanelContext). No new nav state is introduced.
 */
export const WORKBENCH_STEP_IDS = {
  scan: 'scan',
  confirm: 'confirm',
  review: 'review',
} as const;
export type WorkbenchStepId = (typeof WORKBENCH_STEP_IDS)[keyof typeof WORKBENCH_STEP_IDS];

interface WorkbenchStepDescriptor {
  id: WorkbenchStepId;
  number: number;
  label: string;
}

const WORKBENCH_STEPS: readonly WorkbenchStepDescriptor[] = [
  { id: WORKBENCH_STEP_IDS.scan, number: 1, label: __('Scan', 'alt-context') },
  { id: WORKBENCH_STEP_IDS.confirm, number: 2, label: __('Confirm', 'alt-context') },
  { id: WORKBENCH_STEP_IDS.review, number: 3, label: __('Review', 'alt-context') },
];

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
}: WorkbenchStepMapProps): React.JSX.Element => {
  const activeIndex = WORKBENCH_STEPS.findIndex((step) => step.id === activeStep);

  return (
    <nav className="acx-workbench-steps" aria-label={__('Progress', 'alt-context')}>
      <ol className="acx-workbench-steps__list">
        {WORKBENCH_STEPS.map((step, index) => {
          const isCurrent = step.id === activeStep;
          const isComplete = index < activeIndex;
          const itemClassName = [
            'acx-workbench-steps__item',
            isCurrent ? 'acx-workbench-steps__item--current' : '',
            isComplete ? 'acx-workbench-steps__item--complete' : '',
          ]
            .filter(Boolean)
            .join(' ');

          const inner = (
            <>
              <span className="acx-workbench-steps__marker" aria-hidden="true">
                {step.number}
              </span>
              <span className="acx-workbench-steps__label">{step.label}</span>
              {isCurrent ? (
                <span className="acx-workbench-steps__status acx-workbench-steps__status--current">
                  {__('Current', 'alt-context')}
                </span>
              ) : null}
              {isComplete ? (
                <span className="acx-workbench-steps__status acx-workbench-steps__status--complete">
                  <span aria-hidden="true">{'✓'}</span>
                  <span className="screen-reader-text">{__('Completed', 'alt-context')}</span>
                </span>
              ) : null}
            </>
          );

          return (
            <li
              key={step.id}
              className={itemClassName}
              aria-current={isCurrent ? 'step' : undefined}
              data-testid={`acx-workbench-step-${step.id}`}
            >
              {step.id === WORKBENCH_STEP_IDS.review ? (
                <span className="acx-workbench-steps__control">{inner}</span>
              ) : (
                <button
                  type="button"
                  className="acx-workbench-steps__control"
                  onClick={step.id === WORKBENCH_STEP_IDS.scan ? onSelectScan : onSelectConfirm}
                >
                  {inner}
                </button>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};

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

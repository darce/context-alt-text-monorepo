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
import { useJobPipeline } from './workbench/JobPipelineContext';
import { useWorkbenchMediaContext } from './workbench/WorkbenchMediaContext';
import { useReviewSurface } from './workbench/ReviewSurfaceContext';
import { deriveReviewSurfaceActive } from './workbench/mediaFooterCtaState';
import { usePanesParam } from '../hooks/usePanesParam';
import { APP_LINK_VALUES } from '../navigation/appLinks';

export const WorkbenchPage = (): React.JSX.Element => (
  <WorkbenchProvider>
    <WorkbenchPageContent />
  </WorkbenchProvider>
);

const WorkbenchPageContent = (): React.JSX.Element => {
  const { activeSection, recognitionSource, effectiveTargetUrl, activeOverlay, setActiveOverlay } = useWorkbenchNav();
  const { scanRun, status, retryProjectionSync } = useJobPipeline();
  const { detailTruncationNotice } = useWorkbenchMediaContext().mediaQueue;
  const [panes, setPanes] = usePanesParam();

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
      <div className="acx-workbench__panels">
        <SyncStatusIndicator
          activeSection={activeSection}
          pipelinePhase={status.currentPhase}
          projectionState={status.projectionSyncState}
          projectionError={status.projectionError}
          onRetryProjection={retryProjectionSync}
        />
        {activeOverlay ? (
          <section className="acx-workbench__overlay" aria-label={__('Workbench overlay', 'alt-context')}>
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

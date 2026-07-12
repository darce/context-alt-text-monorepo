import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { SyncStatusIndicator } from './workbench/SyncStatusIndicator';
import { ScanTabContent } from './workbench/ScanTabContent';
import { AdvancedDrawer } from './workbench/AdvancedDrawer';
import { ConflictInbox } from './workbench/ConflictInbox';
import { DeadLetterPanel } from './workbench/DeadLetterPanel';
import { WorkbenchProvider, useWorkbenchContext, TAB_IDS, type WorkbenchTab } from './workbench/WorkbenchContext';

interface WorkbenchSection {
  id: WorkbenchTab;
  label: string;
  title: string;
  body: string;
}

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
];

export const WorkbenchPage = (): React.JSX.Element => (
  <WorkbenchProvider>
    <WorkbenchPageContent />
  </WorkbenchProvider>
);

const WorkbenchPageContent = (): React.JSX.Element => {
  const {
    activeSection,
    setActiveSection,
    recognitionSource,
    effectiveTargetUrl,
    activeOverlay,
    setActiveOverlay,
    isOnline,
    isPrimary,
    latestJobId,
    currentPhase,
    projectionSyncState,
    projectionError,
    retryProjectionSync,
    detailTruncationNotice,
  } = useWorkbenchContext();

  const scanSection = WORKBENCH_SECTIONS[0];

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
          <SyncStatusIndicator
            activeSection={activeSection}
            pipelinePhase={currentPhase}
            projectionState={projectionSyncState}
            projectionError={projectionError}
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
                  __('Alt Context is targeting the local recognition service at %s.', 'alt-context'),
                  effectiveTargetUrl,
                )}
              </p>
              <p>{__('Use Settings to switch back to the hosted recognition service.', 'alt-context')}</p>
            </div>
          )}
          {!isOnline && (
            <div className="acx-notice acx-notice--warning">
              {__('Network connection lost. Reconnecting…', 'alt-context')}
            </div>
          )}
          {detailTruncationNotice && <div className="acx-notice acx-notice--info">{detailTruncationNotice}</div>}
          {!isPrimary && !!latestJobId && (
            <div className="acx-notice acx-notice--info">
              {__('This job is being processed in another tab.', 'alt-context')}
            </div>
          )}
          <TabsContent
            value={TAB_IDS.scan}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-scan"
          >
            <h2 id="acx-workbench-section-scan">{scanSection.title}</h2>
            <p>{scanSection.body}</p>

            <ScanTabContent />
          </TabsContent>

          <AdvancedDrawer />
        </div>
      </Tabs>
    </section>
  );
};

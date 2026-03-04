import React from 'react';
import { __ } from '@wordpress/i18n';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { SyncStatusIndicator } from './workbench/SyncStatusIndicator';
import { ScanTabContent } from './workbench/ScanTabContent';
import { BatchTabContent } from './workbench/BatchTabContent';
import { ConfirmTabContent } from './workbench/ConfirmTabContent';
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
  {
    id: TAB_IDS.batch,
    label: __('Batch', 'alt-context'),
    title: __('Batch Operations', 'alt-context'),
    body: __('Group the selected media, run recognition jobs, and prep face scans before publishing.', 'alt-context'),
  },
  {
    id: TAB_IDS.confirm,
    label: __('Confirm', 'alt-context'),
    title: __('Confirm & Publish', 'alt-context'),
    body: __('Compare before/after states, spot-check compliance, and push updates to WordPress media.', 'alt-context'),
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
    recognitionUrlFallback,
    isOnline,
    isPrimary,
    latestJobId,
  } = useWorkbenchContext();

  const scanSection = WORKBENCH_SECTIONS[0];
  const batchSection = WORKBENCH_SECTIONS[1];
  const confirmSection = WORKBENCH_SECTIONS[2];

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
          <SyncStatusIndicator />
          {recognitionUrlFallback && (
            <div className="acx-notice acx-notice--warning">
              {__(
                'Alt Context is using the local recognition URL fallback (http://localhost:8000). Configure acx_recognition_url or ACX_RECOGNITION_URL for this environment.',
                'alt-context',
              )}
            </div>
          )}
          {!isOnline && (
            <div className="acx-notice acx-notice--warning">
              {__('Network connection lost. Reconnecting…', 'alt-context')}
            </div>
          )}
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

          <TabsContent
            value={TAB_IDS.batch}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-batch"
          >
            <h2 id="acx-workbench-section-batch">{batchSection.title}</h2>
            <p>{batchSection.body}</p>
            <BatchTabContent />
          </TabsContent>

          <TabsContent
            value={TAB_IDS.confirm}
            className="acx-workbench__panel"
            aria-live="polite"
            aria-labelledby="acx-workbench-section-confirm"
          >
            <h2 id="acx-workbench-section-confirm">{confirmSection.title}</h2>
            <p>{confirmSection.body}</p>
            <ConfirmTabContent />
          </TabsContent>
        </div>
      </Tabs>
    </section>
  );
};

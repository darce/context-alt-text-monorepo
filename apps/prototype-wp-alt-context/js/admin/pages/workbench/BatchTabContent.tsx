import { __ } from '@wordpress/i18n';
import { BatchPanel, RecentJobsPanel } from './Panels';
import { useWorkbenchContext } from './WorkbenchContext';

export const BatchTabContent = (): React.JSX.Element => {
  const { selectedMedia, jobHistory, jobStatuses, jobId, handleSelectJobFromHistory, clearHistory } =
    useWorkbenchContext();
  return (
    <>
      {selectedMedia.length === 0 ? (
        <div className="acx-apply-panel acx-apply-panel--empty">
          <h3>{__('No media selected for batch analysis', 'alt-context')}</h3>
          <p>{__('Go to the Scan tab to select media items you want to analyze together.', 'alt-context')}</p>
          <a href="#/workbench?tab=scan" className="acx-button acx-button--secondary">
            {__('Go to Scan tab', 'alt-context')}
          </a>
        </div>
      ) : (
        <BatchPanel items={selectedMedia} />
      )}

      <RecentJobsPanel
        jobs={jobHistory}
        statuses={jobStatuses}
        activeJobId={jobId ?? null}
        onSelect={handleSelectJobFromHistory}
        onClear={clearHistory}
      />
    </>
  );
};

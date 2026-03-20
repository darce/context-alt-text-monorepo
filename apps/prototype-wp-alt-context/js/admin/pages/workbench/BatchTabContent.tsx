import { __ } from '@wordpress/i18n';
import { RecentJobsPanel } from './Panels';
import { useWorkbenchContext } from './WorkbenchContext';

export const BatchTabContent = (): React.JSX.Element => {
  const { jobHistory, jobStatuses, jobId, handleSelectJobFromHistory, clearHistory } = useWorkbenchContext();
  return (
    <>
      <div className="acx-apply-panel acx-apply-panel--empty">
        <h3>{__('Batch operations moved to Dashboard', 'alt-context')}</h3>
        <p>
          {__(
            'Start new recognition batches from the Dashboard. Come back to Workbench to inspect the scan queue or confirm the latest results.',
            'alt-context',
          )}
        </p>
        <div className="acx-dashboard__actions">
          <a href="#/dashboard" className="acx-button">
            {__('Open Dashboard', 'alt-context')}
          </a>
          <a href="#/workbench?tab=confirm" className="acx-button acx-button--secondary">
            {__('Go to Confirm tab', 'alt-context')}
          </a>
        </div>
      </div>

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

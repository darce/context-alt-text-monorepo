import { BatchPanel, RecentJobsPanel } from './Panels';
import { useWorkbenchContext } from './WorkbenchContext';

export const BatchTabContent = (): React.JSX.Element => {
  const {
    selectedMedia,
    jobHistory,
    jobStatuses,
    jobId,
    handleSelectJobFromHistory,
    clearHistory,
  } = useWorkbenchContext();
  return (
    <>
      <BatchPanel items={selectedMedia} />
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

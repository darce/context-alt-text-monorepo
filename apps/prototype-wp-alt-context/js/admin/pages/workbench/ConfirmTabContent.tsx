import React from 'react';
import { ConfirmPanel, RecentJobsPanel, rosterClustersUrl } from './Panels';
import { useWorkbenchContext } from './WorkbenchContext';

export const ConfirmTabContent = (): React.JSX.Element => {
  const {
    jobId,
    statusText,
    cluster,
    isScanRunning,
    clusterMessage,
    scanProgress,
    etaSeconds,
    isPrimary,
    latestJobId,
    jobHistory,
    jobStatuses,
    handleSelectJobFromHistory,
    clearHistory,
  } = useWorkbenchContext();
  return (
    <>
      <ConfirmPanel
        jobId={jobId ?? null}
        status={statusText}
        onCluster={cluster}
        isClustering={isScanRunning}
        progress={scanProgress}
        clusterMessage={clusterMessage}
        onViewClusters={() => window.location.assign(rosterClustersUrl())}
        etaSeconds={etaSeconds}
        isSynced={!isPrimary && !!latestJobId}
      />
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

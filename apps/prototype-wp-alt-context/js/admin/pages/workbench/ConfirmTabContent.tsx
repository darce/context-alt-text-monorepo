import React from 'react';
import { __ } from '@wordpress/i18n';
import { ConfirmPanel, RecentJobsPanel, rosterClustersUrl } from './Panels';
import { useWorkbenchContext } from './WorkbenchContext';

export const ConfirmTabContent = (): React.JSX.Element => {
  const {
    jobId,
    statusText,
    cluster,
    isScanRunning,
    clusterMessage,
    clusterProgress,
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
      <div className="acx-workbench-help-card">
        <h3>{__('What is Clustering?', 'alt-context')}</h3>
        <p>
          {__(
            'Clustering groups similar face embeddings detected during the scan into cohesive identities. This allows you to label an entire group of faces (e.g., "John Doe") at once, rather than naming every individual photo.',
            'alt-context',
          )}
        </p>
      </div>
      <ConfirmPanel
        jobId={jobId ?? null}
        status={statusText}
        onCluster={cluster}
        isClustering={isScanRunning}
        progress={clusterProgress}
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

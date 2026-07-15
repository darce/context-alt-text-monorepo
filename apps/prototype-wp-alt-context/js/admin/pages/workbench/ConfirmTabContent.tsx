import React from 'react';
import { __ } from '@wordpress/i18n';
import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import { ConfirmPanel, RecentJobsPanel, rosterClustersUrl } from './Panels';
import { useJobPipeline } from './JobPipelineContext';

export const ConfirmTabContent = (): React.JSX.Element => {
  const { scanRun, status, history, cluster, handleSelectJobFromHistory, clearHistory } = useJobPipeline();
  // RES-15: container owns offline signal; presentational ConfirmPanel receives props only.
  const offline = useSyncOffline();
  const remoteGate = useRemoteActionGate(offline);
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
        jobId={history.jobId ?? null}
        status={scanRun.statusText}
        onCluster={cluster}
        isClustering={scanRun.isScanning}
        progress={status.clusterProgress}
        clusterMessage={status.clusterMessage}
        onViewClusters={() => window.location.assign(rosterClustersUrl())}
        etaSeconds={scanRun.etaSeconds}
        isSynced={scanRun.isSynced}
        remoteActionDisabled={remoteGate.disabled}
        remoteActionTitle={remoteGate.title}
        remoteActionAriaDisabled={remoteGate['aria-disabled']}
      />
      <RecentJobsPanel
        jobs={history.jobHistory}
        statuses={history.jobStatuses}
        activeJobId={history.jobId ?? null}
        historySource={history.historySource}
        onSelect={handleSelectJobFromHistory}
        onClear={clearHistory}
      />
    </>
  );
};

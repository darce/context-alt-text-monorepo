import React from 'react';
import { __ } from '@wordpress/i18n';
import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import {
  CLUSTERING_DISCLOSURE_BODY,
  CLUSTERING_DISCLOSURE_SUMMARY,
} from './confirmTabCopy';
import { ConfirmPanel, RecentJobsPanel, rosterClustersUrl } from './Panels';
import { useJobPipeline } from './JobPipelineContext';

export const ConfirmTabContent = (): React.JSX.Element => {
  const { scanRun, status, history, cluster, handleSelectJobFromHistory, clearHistory } = useJobPipeline();
  // RES-15: container owns offline signal; presentational ConfirmPanel receives props only.
  const offline = useSyncOffline();
  const remoteGate = useRemoteActionGate(offline);
  return (
    <>
      <details className="acx-workbench-help-card">
        <summary>{__(CLUSTERING_DISCLOSURE_SUMMARY, 'alt-context')}</summary>
        <p>{__(CLUSTERING_DISCLOSURE_BODY, 'alt-context')}</p>
      </details>
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

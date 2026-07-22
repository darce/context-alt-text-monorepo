import React from 'react';
import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import {
  CLUSTERING_DISCLOSURE_BODY,
  CLUSTERING_DISCLOSURE_SUMMARY,
} from './confirmTabCopy';
import { ConfirmPanel, RecentJobsPanel, rosterUrl } from './Panels';
import { useJobPipeline } from './JobPipelineContext';

export const ConfirmTabContent = (): React.JSX.Element => {
  const { scanRun, status, history, cluster, handleSelectJobFromHistory, clearHistory } = useJobPipeline();
  // RES-15: container owns offline signal; presentational ConfirmPanel receives props only.
  const offline = useSyncOffline();
  const remoteGate = useRemoteActionGate(offline);
  return (
    <>
      <details className="acx-workbench-help-card">
        <summary>{CLUSTERING_DISCLOSURE_SUMMARY}</summary>
        <p>{CLUSTERING_DISCLOSURE_BODY}</p>
      </details>
      <ConfirmPanel
        jobId={history.jobId ?? null}
        status={scanRun.statusText}
        onCluster={cluster}
        isClustering={scanRun.isScanning}
        progress={status.clusterProgress}
        clusterMessage={status.clusterMessage}
        onViewClusters={() => window.location.assign(rosterUrl())}
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

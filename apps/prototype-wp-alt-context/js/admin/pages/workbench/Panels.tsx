import { __, _n, sprintf } from '@wordpress/i18n';

import type { JobProgress } from '../../api/recognition/types/scan';
import type { RecognitionHistorySource } from '../../hooks/recognitionJobHistoryUtils';
import type { ScanRunViewModel } from './JobPipelineContext';
import { JOB_PHASE_PRESENTATION } from './phasePresentation';
import { formatSyncJobPhase } from './syncPresentation';
export { mediaEditUrl, rosterClustersUrl } from '../../utils/adminUrls';

export const isClusteringActive = (phase?: string | null): boolean => phase === 'clustering' || phase === 'retrying';

interface ScanActionPanelProps {
  scanRun: ScanRunViewModel;
  onCancelScan?: () => void;
  onRetryStream?: () => void;
}

export const ScanActionPanel = ({ scanRun, onCancelScan, onRetryStream }: ScanActionPanelProps): React.JSX.Element => {
  const {
    isScanning,
    isCancelling,
    statusText,
    jobId,
    errorMessage,
    progress,
    batchRunStatus,
    stallSeconds,
    etaSeconds,
    isSynced,
  } = scanRun;

  // progress.phase is optional; an absent phase falls back to the shared
  // scan/images presentation (any scan-family entry carries the same
  // processed builder + aria label references).
  const progressPresentation = progress?.phase
    ? JOB_PHASE_PRESENTATION[progress.phase]
    : JOB_PHASE_PRESENTATION.detecting;

  return (
    <div className="acx-apply-panel">
      {onCancelScan && (
        <button
          type="button"
          className="acx-link-button"
          onClick={onCancelScan}
          disabled={Boolean(isCancelling) || !isScanning}
        >
          {isCancelling ? __('Cancelling…', 'alt-context') : __('Cancel scan', 'alt-context')}
        </button>
      )}
      {statusText && (
        <p className="acx-apply-panel__status">
          {sprintf(__('Job %s: %s', 'alt-context'), jobId ?? __('pending', 'alt-context'), statusText)}
        </p>
      )}
      {typeof stallSeconds === 'number' && (
        <div className="acx-apply-panel__status acx-apply-panel__status--warning">
          <p>{sprintf(__('Stuck - last update %s ago', 'alt-context'), formatDuration(stallSeconds))}</p>
          <div className="acx-apply-panel__actions">
            <button type="button" className="acx-link-button" onClick={onRetryStream} disabled={!onRetryStream}>
              {__('Retry', 'alt-context')}
            </button>
            {onCancelScan && (
              <button
                type="button"
                className="acx-link-button"
                onClick={onCancelScan}
                disabled={Boolean(isCancelling) || !isScanning}
              >
                {__('Cancel', 'alt-context')}
              </button>
            )}
          </div>
        </div>
      )}
      {progress && progress.total > 0 && (
        <>
          {progress.phase && (
            <p className="acx-apply-panel__status">
              {sprintf(__('Phase: %s', 'alt-context'), formatJobPhase(progress.phase))}
            </p>
          )}
          <p className="acx-apply-panel__status">
            {progressPresentation.processed({
              completed: progress.completed,
              total: progress.total,
              imagesProcessed: progress.images_processed,
              facesFound: progress.faces_found,
            })}
          </p>
          {isClusteringActive(progress.phase) &&
            typeof progress.retry_count === 'number' &&
            progress.retry_count > 0 && (
              <p className="acx-apply-panel__status">
                {sprintf(_n('Retry %d', 'Retry %d', progress.retry_count, 'alt-context'), progress.retry_count)}
                {progress.last_error_code
                  ? sprintf(__(' (last error: %s)', 'alt-context'), progress.last_error_code)
                  : ''}
              </p>
            )}
          <progress
            className="acx-apply-panel__progress"
            value={Math.min(progress.completed, progress.total)}
            max={progress.total}
            aria-label={progressPresentation.progressAriaLabel}
          />
          {typeof etaSeconds === 'number' && (
            <p className="acx-apply-panel__eta">
              {sprintf(__('Remaining: %s', 'alt-context'), formatDuration(etaSeconds))}
            </p>
          )}
          {isSynced && <p className="acx-apply-panel__synced">{__('Synced', 'alt-context')}</p>}
        </>
      )}
      {batchRunStatus && batchRunStatus.submitted_total > 0 && (
        <>
          <p className="acx-apply-panel__status">
            {(() => {
              const processedTotal =
                batchRunStatus.completed_total + batchRunStatus.failed_total + batchRunStatus.cancelled_total;
              return batchRunStatus.failed_total > 0
                ? sprintf(
                    __('Processed %1$d/%2$d (%3$d failed)', 'alt-context'),
                    processedTotal,
                    batchRunStatus.submitted_total,
                    batchRunStatus.failed_total,
                  )
                : sprintf(__('Processed %1$d/%2$d', 'alt-context'), processedTotal, batchRunStatus.submitted_total);
            })()}
          </p>
          {batchRunStatus.failed_batches.length > 0 && (
            <details className="acx-apply-panel__status">
              <summary>{__('Failed batches', 'alt-context')}</summary>
              <ul className="acx-apply-panel__list">
                {batchRunStatus.failed_batches.map((batch) => (
                  <li key={`${batch.batch_index}-${batch.error_code}`}>
                    {sprintf(
                      __('Batch %1$d (%2$d items): %3$s', 'alt-context'),
                      batch.batch_index + 1,
                      batch.media_ids.length,
                      batch.error_message,
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
      {errorMessage && <p className="acx-apply-panel__status acx-apply-panel__status--error">{errorMessage}</p>}
    </div>
  );
};

interface ConfirmPanelProps {
  jobId: string | null;
  status?: string;
  onCluster: () => void;
  isClustering: boolean;
  clusterMessage?: string | null;
  onViewClusters: () => void;
  progress?: JobProgress | null;
  etaSeconds?: number | null;
  isSynced?: boolean;
  /** Remote-compute offline gate (RES-15) — container threads useRemoteActionGate props. */
  remoteActionDisabled?: boolean;
  remoteActionTitle?: string;
  remoteActionAriaDisabled?: true;
}

export const ConfirmPanel = ({
  jobId,
  status,
  onCluster,
  isClustering,
  clusterMessage,
  onViewClusters,
  progress,
  etaSeconds,
  isSynced,
  remoteActionDisabled = false,
  remoteActionTitle,
  remoteActionAriaDisabled,
}: ConfirmPanelProps) => (
  <div className="acx-apply-panel">
    <p>{__('Review the most recent recognition job and cluster the detected embeddings.', 'alt-context')}</p>
    <ul className="acx-apply-panel__list">
      <li>
        <strong>{__('Latest job', 'alt-context')}</strong> — {jobId ?? __('No job yet', 'alt-context')}
      </li>
      <li>
        {__('Status', 'alt-context')} — {status ?? __('Pending', 'alt-context')}
      </li>
    </ul>
    <button
      type="button"
      className="acx-apply-panel__scan"
      onClick={onCluster}
      disabled={isClustering || remoteActionDisabled}
      aria-disabled={remoteActionAriaDisabled}
      title={remoteActionTitle}
    >
      {isClustering ? __('Clustering faces…', 'alt-context') : __('Cluster the latest job results', 'alt-context')}
    </button>
    <button type="button" className="acx-link-button" onClick={onViewClusters} disabled={!jobId}>
      {__('Open clusters in roster', 'alt-context')}
    </button>
    {progress && progress.total > 0 && (
      <>
        {progress.phase && (
          <p className="acx-apply-panel__status">
            {sprintf(__('Phase: %s', 'alt-context'), formatJobPhase(progress.phase))}
          </p>
        )}
        <p className="acx-apply-panel__status">
          {sprintf(__('Processed %d/%d identities', 'alt-context'), progress.completed, progress.total)}
        </p>
        {typeof progress.clusters_created === 'number' && (
          <p className="acx-apply-panel__status">
            {sprintf(__('Clusters created: %d', 'alt-context'), progress.clusters_created)}
          </p>
        )}
        {typeof progress.retry_count === 'number' && progress.retry_count > 0 && (
          <p className="acx-apply-panel__status">
            {sprintf(_n('Retry %d', 'Retry %d', progress.retry_count, 'alt-context'), progress.retry_count)}
            {progress.last_error_code ? sprintf(__(' (last error: %s)', 'alt-context'), progress.last_error_code) : ''}
          </p>
        )}
        <progress
          className="acx-apply-panel__progress"
          value={Math.min(progress.completed, progress.total)}
          max={progress.total}
          aria-label={__('Clustering progress', 'alt-context')}
        />
        {etaSeconds !== null && etaSeconds !== undefined && (
          <p className="acx-apply-panel__eta">
            {sprintf(__('Remaining: %s', 'alt-context'), formatDuration(etaSeconds))}
          </p>
        )}
        {isSynced && <p className="acx-apply-panel__synced">{__('Synced', 'alt-context')}</p>}
      </>
    )}
    {clusterMessage && <p className="acx-apply-panel__status">{clusterMessage}</p>}
  </div>
);

interface RecentJobsPanelProps {
  jobs: string[];
  statuses: Record<string, string>;
  activeJobId: string | null;
  onSelect: (jobId: string) => void;
  onClear: () => void;
  historySource?: RecognitionHistorySource;
}

export const RecentJobsPanel = ({
  jobs,
  statuses,
  activeJobId,
  onSelect,
  onClear,
  historySource = 'unavailable',
}: RecentJobsPanelProps) => (
  <div className="acx-apply-panel">
    <div className="acx-apply-panel__header">
      <strong>{__('Recent jobs', 'alt-context')}</strong>
      {jobs.length > 0 && historySource === 'browser_local_fallback' && (
        <button type="button" onClick={onClear} className="acx-link-button">
          {__('Clear history', 'alt-context')}
        </button>
      )}
    </div>
    {historySource === 'browser_local_fallback' ? (
      <p>{__('Showing jobs remembered in this browser only.', 'alt-context')}</p>
    ) : null}
    {historySource === 'unavailable' && jobs.length === 0 ? (
      <p>{__('Durable recent activity is unavailable right now.', 'alt-context')}</p>
    ) : null}
    {jobs.length === 0 ? (
      <p>{__('No previous jobs yet.', 'alt-context')}</p>
    ) : (
      <ul className="acx-job-history">
        {jobs.map((id) => (
          <li key={id}>
            <button
              type="button"
              className={id === activeJobId ? 'acx-job-history__item is-active' : 'acx-job-history__item'}
              onClick={() => onSelect(id)}
            >
              <span>{id}</span>
              <em>{statuses[id] ?? __('Unknown', 'alt-context')}</em>
            </button>
          </li>
        ))}
      </ul>
    )}
  </div>
);

const formatDuration = (seconds: number): string => {
  if (seconds < 60) {
    return sprintf(_n('%d second', '%d seconds', seconds, 'alt-context'), seconds);
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (remainingSeconds === 0) {
    return sprintf(_n('%d minute', '%d minutes', minutes, 'alt-context'), minutes);
  }
  return sprintf(__('%d min %d sec', 'alt-context'), minutes, remainingSeconds);
};

const formatJobPhase = (phase: NonNullable<JobProgress['phase']>): string => formatSyncJobPhase(phase);

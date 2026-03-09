import { __, _n, sprintf } from '@wordpress/i18n';

import type { JobProgress } from '../../api/recognition/types/scan';
export { mediaEditUrl, rosterClustersUrl } from '../../utils/adminUrls';

interface ScanActionPanelProps {
  selectedCount: number;
  onScanFaces: () => void;
  onCancelScan?: () => void;
  isScanning: boolean;
  isCancelling?: boolean;
  statusText?: string;
  jobId?: string | null;
  errorMessage?: string | null;
  progress?: JobProgress | null;
  etaSeconds?: number | null;
  isSynced?: boolean;
}

export const ScanActionPanel = ({
  selectedCount,
  onScanFaces,
  onCancelScan,
  isScanning,
  isCancelling,
  statusText,
  jobId,
  errorMessage,
  progress,
  etaSeconds,
  isSynced,
}: ScanActionPanelProps): React.JSX.Element => (
  <div className="acx-apply-panel">
    <p>
      {selectedCount === 0
        ? __('Select media items from the queue to analyze them.', 'alt-context')
        : sprintf(
            _n('Ready to analyze %d media item.', 'Ready to analyze %d media items.', selectedCount, 'alt-context'),
            selectedCount,
          )}
    </p>
    <button
      type="button"
      className="acx-apply-panel__scan"
      onClick={onScanFaces}
      disabled={isScanning || selectedCount === 0}
    >
      {isScanning ? __('Scanning media…', 'alt-context') : __('Analyze selected media', 'alt-context')}
    </button>
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
    {progress && progress.total > 0 && (
      <>
        {progress.phase && (
          <p className="acx-apply-panel__status">
            {sprintf(__('Phase: %s', 'alt-context'), formatJobPhase(progress.phase))}
          </p>
        )}
        <p className="acx-apply-panel__status">
          {sprintf(
            __('Processed %d/%d images', 'alt-context'),
            progress.images_processed ?? progress.completed,
            progress.total,
          )}
          {typeof progress.faces_found === 'number'
            ? sprintf(__(' · %d faces found', 'alt-context'), progress.faces_found)
            : ''}
        </p>
        <progress
          className="acx-apply-panel__progress"
          value={Math.min(progress.completed, progress.total)}
          max={progress.total}
          aria-label={__('Scan progress', 'alt-context')}
        />
        {typeof etaSeconds === 'number' && (
          <p className="acx-apply-panel__eta">
            {sprintf(__('Remaining: %s', 'alt-context'), formatDuration(etaSeconds))}
          </p>
        )}
        {isSynced && <p className="acx-apply-panel__synced">{__('Synced', 'alt-context')}</p>}
      </>
    )}
    {errorMessage && <p className="acx-apply-panel__status acx-apply-panel__status--error">{errorMessage}</p>}
  </div>
);

export const BatchPanel = ({ items }: { items: { id: number; title: string; altText: string | null }[] }) => (
  <div className="acx-apply-panel">
    <p>
      {sprintf(
        _n(
          'You have %d media item ready for analysis.',
          'You have %d media items ready for analysis.',
          items.length,
          'alt-context',
        ),
        items.length,
      )}
    </p>
    <ul className="acx-apply-panel__list">
      {items.map((item) => (
        <li key={item.id}>
          <strong>{item.title}</strong> — {item.altText ?? __('No alt text yet', 'alt-context')}
        </li>
      ))}
    </ul>
  </div>
);

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
    <button type="button" className="acx-apply-panel__scan" onClick={onCluster} disabled={isClustering}>
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
}

export const RecentJobsPanel = ({ jobs, statuses, activeJobId, onSelect, onClear }: RecentJobsPanelProps) => (
  <div className="acx-apply-panel">
    <div className="acx-apply-panel__header">
      <strong>{__('Recent jobs', 'alt-context')}</strong>
      {jobs.length > 0 && (
        <button type="button" onClick={onClear} className="acx-link-button">
          {__('Clear history', 'alt-context')}
        </button>
      )}
    </div>
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

const formatJobPhase = (phase: NonNullable<JobProgress['phase']>): string => {
  switch (phase) {
    case 'queued':
      return __('Queued', 'alt-context');
    case 'detecting':
      return __('Detecting', 'alt-context');
    case 'clustering':
      return __('Clustering', 'alt-context');
    case 'awaiting_projection':
      return __('Projecting', 'alt-context');
    case 'complete':
      return __('Complete', 'alt-context');
    default:
      return phase;
  }
};

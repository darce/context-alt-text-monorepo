import { __, _n, sprintf } from '@wordpress/i18n';

interface ScanActionPanelProps {
  selectedCount: number;
  onScanFaces: () => void;
  isScanning: boolean;
  statusText?: string;
  jobId?: string | null;
  errorMessage?: string | null;
}

export const ScanActionPanel = ({
  selectedCount,
  onScanFaces,
  isScanning,
  statusText,
  jobId,
  errorMessage,
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
    {statusText && (
      <p className="acx-apply-panel__status">
        {sprintf(__('Job %s: %s', 'alt-context'), jobId ?? __('pending', 'alt-context'), statusText)}
      </p>
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
}

export const ConfirmPanel = ({
  jobId,
  status,
  onCluster,
  isClustering,
  clusterMessage,
  onViewClusters,
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

export const mediaEditUrl = (mediaId: number): string =>
  `${window.location.origin}/wp-admin/post.php?post=${mediaId}&action=edit`;

export const rosterClustersUrl = (): string =>
  `${window.location.origin}/wp-admin/admin.php?page=alt-context-roster&tab=clusters`;

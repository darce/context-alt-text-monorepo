import { __, _n, sprintf } from '@wordpress/i18n';

import type { JobProgress } from '../../api/recognition/types/scan';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { RecognitionHistorySource } from '../../hooks/recognitionJobHistoryUtils';
import { CONFIRM_NO_JOB_ZERO_STATE, CONFIRM_PANEL_INTRO } from './confirmTabCopy';
import type { ScanRunViewModel } from './JobPipelineContext';
import { JOB_PHASE_PRESENTATION } from './phasePresentation';
import { formatSyncJobPhase } from './syncPresentation';
import { SYNC_VOCABULARY } from './syncVocabulary';
import { EmptyState, EmptyStateVariant } from '../../components/ui/EmptyState';
import { toWorkbench } from '../../navigation/appLinks';
export { mediaEditUrl, rosterUrl } from '../../utils/adminUrls';

export const isClusteringActive = (phase?: string | null): boolean => phase === 'clustering' || phase === 'retrying';

type ScanActionPanelVariant = 'default' | 'compact';

/** Idle region (d) copy — short description when no cancel/progress chrome is shown. */
const SCAN_REGION_DESCRIPTION = __(
  'Scan your library for images that still need descriptive metadata, filtering by status or search term.',
  'alt-context',
);

/** Per-tick patterns that must stay visual-only when progressPhase is absent (L3R-01 / L3V-03). */
const TICKING_STATUS_TEXT = /\d+\s*\/\s*\d+|\d+\s*s\b/;

/**
 * Coarse AT announcement for the job live region (L3R-01 residual).
 * Prefer progress phase labels (stable across SSE ticks). Fall back to statusText
 * only when it has no N/M count or countdown pattern — per-tick "Processed N/M"
 * and "starting in Ns" stay visual-only (L3V-03).
 */
export const buildCoarseJobAnnouncement = ({
  jobId,
  statusText,
  progressPhase,
}: {
  jobId?: string | null;
  statusText?: string;
  progressPhase?: JobProgress['phase'] | null;
}): string | null => {
  if (!statusText && !progressPhase) {
    return null;
  }
  const jobLabel = jobId ?? __('pending', 'alt-context');
  if (progressPhase) {
    return sprintf(__('Job %s: %s', 'alt-context'), jobLabel, formatSyncJobPhase(progressPhase));
  }
  // No phase: announce stable status only (terminal words, "Starting scan…", etc.).
  if (statusText && !TICKING_STATUS_TEXT.test(statusText)) {
    return sprintf(__('Job %s: %s', 'alt-context'), jobLabel, statusText);
  }
  return null;
};

/**
 * Compact strip leading verb from pipeline phase (L3R-06). Falls back to job
 * progress phase, then the generic scanning headline.
 */
const compactLeadingVerb = (
  currentPhase?: PipelinePhase | null,
  progressPhase?: JobProgress['phase'] | null,
): string => {
  if (currentPhase === 'clustering') {
    return SYNC_VOCABULARY.clusteringHeadline;
  }
  if (currentPhase === 'projecting') {
    return SYNC_VOCABULARY.resultsSyncingHeadline;
  }
  if (currentPhase === 'scanning') {
    return SYNC_VOCABULARY.scanningHeadline;
  }
  if (progressPhase === 'clustering' || progressPhase === 'retrying') {
    return SYNC_VOCABULARY.clusteringHeadline;
  }
  if (progressPhase === 'awaiting_projection') {
    return SYNC_VOCABULARY.resultsSyncingHeadline;
  }
  if (progressPhase === 'queued') {
    return sprintf(__('%s…', 'alt-context'), SYNC_VOCABULARY.phaseQueued);
  }
  return SYNC_VOCABULARY.scanningHeadline;
};

interface ScanActionPanelProps {
  scanRun: ScanRunViewModel;
  onCancelScan?: () => void;
  onRetryStream?: () => void;
  /** Compact single-row strip for the active-job chrome (E21-18 S1). */
  variant?: ScanActionPanelVariant;
  /**
   * When the compact strip owns progress + cancel, suppress those controls here
   * so only statusText / stall / batch failures / errors remain (L3R-02).
   */
  suppressPrimaryChrome?: boolean;
  /** Pipeline phase for compact leading verb (L3R-06). */
  currentPhase?: PipelinePhase | null;
}

export const ScanActionPanel = ({
  scanRun,
  onCancelScan,
  onRetryStream,
  variant = 'default',
  suppressPrimaryChrome = false,
  currentPhase = null,
}: ScanActionPanelProps): React.JSX.Element => {
  const {
    isScanning,
    isCancelling,
    statusText,
    jobId,
    errorMessage,
    onRetryClustering,
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

  // L3R-01 residual: live region text is phase/terminal only; statusText stays visual.
  const coarseAnnouncement = buildCoarseJobAnnouncement({
    jobId,
    statusText,
    progressPhase: progress?.phase,
  });

  if (variant === 'compact') {
    // Strip keeps progress/phase/cancel only — full panel retains backend job messages
    // so operators still see a single source for statusText (no duplicate live regions).
    const pct =
      progress && progress.total > 0
        ? Math.min(100, Math.round((progress.completed / progress.total) * 100))
        : null;
    const phaseLabel = progress?.phase ? formatJobPhase(progress.phase) : null;
    const summaryParts = [
      compactLeadingVerb(currentPhase, progress?.phase),
      pct !== null ? `${pct}%` : null,
      phaseLabel ? sprintf(__('phase: %s', 'alt-context'), phaseLabel) : null,
    ].filter(Boolean);

    return (
      <div className="acx-apply-panel acx-apply-panel--compact" data-variant="compact">
        <p className="acx-apply-panel__status acx-apply-panel__status--compact">{summaryParts.join(' · ')}</p>
        {progress && progress.total > 0 && (
          <progress
            className="acx-apply-panel__progress acx-apply-panel__progress--compact"
            value={Math.min(progress.completed, progress.total)}
            max={progress.total}
            aria-label={progressPresentation.progressAriaLabel}
          />
        )}
        {onCancelScan && isScanning && (
          <button
            type="button"
            className="acx-link-button"
            onClick={onCancelScan}
            disabled={Boolean(isCancelling)}
          >
            {isCancelling ? __('Cancelling…', 'alt-context') : __('Cancel', 'alt-context')}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="acx-apply-panel">
      {/* L3R-05: hide permanently-disabled cancel when idle; L3R-02: strip owns cancel while active. */}
      {onCancelScan && isScanning && !suppressPrimaryChrome && (
        <button
          type="button"
          className="acx-link-button"
          onClick={onCancelScan}
          disabled={Boolean(isCancelling)}
        >
          {isCancelling ? __('Cancelling…', 'alt-context') : __('Cancel scan', 'alt-context')}
        </button>
      )}
      {/* L3R-05: mockup region (d) short description when truly idle (no job chrome). */}
      {!isScanning && !statusText && !errorMessage && !(progress && progress.total > 0) && !batchRunStatus && (
        <p className="acx-apply-panel__status">{SCAN_REGION_DESCRIPTION}</p>
      )}
      {/* Visual status updates every tick; live region is phase-stable (L3R-01 residual). */}
      {statusText && (
        <p className="acx-apply-panel__status" data-testid="scan-status-visual">
          {sprintf(__('Job %s: %s', 'alt-context'), jobId ?? __('pending', 'alt-context'), statusText)}
        </p>
      )}
      {coarseAnnouncement && (
        <p
          className="screen-reader-text"
          role="status"
          aria-live="polite"
          data-testid="scan-status-announce"
        >
          {coarseAnnouncement}
        </p>
      )}
      {typeof stallSeconds === 'number' && (
        <div className="acx-apply-panel__status acx-apply-panel__status--warning">
          <p>{sprintf(__('Stuck - last update %s ago', 'alt-context'), formatDuration(stallSeconds))}</p>
          <div className="acx-apply-panel__actions">
            <button type="button" className="acx-link-button" onClick={onRetryStream} disabled={!onRetryStream}>
              {__('Retry', 'alt-context')}
            </button>
            {/* L3R-07: strip owns Cancel while suppressPrimaryChrome — avoid dual Cancel. */}
            {onCancelScan && isScanning && !suppressPrimaryChrome && (
              <button
                type="button"
                className="acx-link-button"
                onClick={onCancelScan}
                disabled={Boolean(isCancelling)}
              >
                {__('Cancel', 'alt-context')}
              </button>
            )}
          </div>
        </div>
      )}
      {progress && progress.total > 0 && (
        <>
          {/* Unique detail kept while strip owns the progress bar (L3R-02). */}
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
          {!suppressPrimaryChrome && (
            <progress
              className="acx-apply-panel__progress"
              value={Math.min(progress.completed, progress.total)}
              max={progress.total}
              aria-label={progressPresentation.progressAriaLabel}
            />
          )}
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
      {errorMessage && (
        <div className="acx-apply-panel__status acx-apply-panel__status--error" role="alert">
          <p>{errorMessage}</p>
          {onRetryClustering && (
            <div className="acx-apply-panel__actions">
              <button type="button" className="acx-link-button" onClick={onRetryClustering}>
                {__('Retry clustering', 'alt-context')}
              </button>
            </div>
          )}
        </div>
      )}
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
    <p>{CONFIRM_PANEL_INTRO}</p>
    {jobId == null ? (
      <p className="acx-apply-panel__status">{CONFIRM_NO_JOB_ZERO_STATE}</p>
    ) : (
      <ul className="acx-apply-panel__list">
        <li>
          <strong>{__('Latest job', 'alt-context')}</strong> — {jobId}
        </li>
        <li>
          {__('Status', 'alt-context')} — {status ?? __('Pending', 'alt-context')}
        </li>
      </ul>
    )}
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
      {__('Open roster', 'alt-context')}
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
    {jobs.length === 0 ? historySource === 'unavailable' ? (
      <EmptyState
        variant={EmptyStateVariant.UNAVAILABLE}
        heading={__('Recent jobs are unavailable', 'alt-context')}
        body={__('Recent activity could not be loaded. Run a scan to start a new job.', 'alt-context')}
        action={{ label: __('Run a scan', 'alt-context'), href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
      />
    ) : (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={__('No previous jobs yet.', 'alt-context')}
        body={__('Run a scan to find faces in your media library.', 'alt-context')}
        action={{ label: __('Run a scan', 'alt-context'), href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
      />
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

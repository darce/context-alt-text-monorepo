import { ChangeEvent, useState } from 'react';
import * as Select from '@radix-ui/react-select';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock,
  Loader2,
  XCircle,
} from 'lucide-react';
import { __, sprintf } from '@wordpress/i18n';
import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { WorkbenchMediaStatus } from '../../api/workbenchMediaApi';
import { MediaSelectionTableBody } from './MediaSelectionTableBody';
import { MediaAnalyzeCta } from './MediaAnalyzeCta';
import { MediaSummaryBar } from './MediaSummaryBar';
import { BulkDescribeReviewLink } from './BulkDescribeReviewLink';

import { Checkbox } from '../../../components/ui/checkbox';
import { useBulkDescribe } from '../../hooks/useBulkDescribe';
import type { DescribeRunProgress } from '../../hooks/useDescribeRunProgress';
import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import { DESCRIBE_RUN_STATUS, type DescribeRunStatus } from '../../api/describeApi';
import { useWorkbenchMediaContext } from './WorkbenchMediaContext';
import { SYNC_VOCABULARY } from './syncPresentation';

interface MediaSelectionProps {
  collapsed?: boolean;
  onExpand?: () => void;
}

export const MediaSelection = ({ collapsed = false, onExpand }: MediaSelectionProps): React.JSX.Element => {
  const { selection: mediaSelection, filters, mediaQueue } = useWorkbenchMediaContext();
  // RES-15: container owns offline signal; BulkDescribeCta is pure presentational.
  const offline = useSyncOffline();
  const remoteGate = useRemoteActionGate(offline);
  const { selection, toggleRow, toggleAll } = mediaSelection;
  const {
    searchQuery,
    handleSearchChange: onSearchChange,
    statusFilter,
    handleStatusChange: onStatusFilterChange,
    currentPage,
    perPage,
    setPerPage: onPerPageChange,
    setCurrentPage: onPageChange,
  } = filters;
  const { mediaQuery, statusMessage } = mediaQueue;

  const mediaData = mediaQuery.data;
  const items = mediaQuery.itemsWithIdentities ?? mediaData?.items ?? [];
  const isLoading = mediaQuery.isPending && items.length === 0;
  const isError = mediaQuery.isError;
  const onRetry = () => void mediaQuery.refetch();
  const totalPages = mediaData?.totalPages ?? 1;
  const areAllPageRowsChecked =
    items.length > 0 && items.every((item: WorkbenchMediaItem) => selection[item.id.toString()]);
  const identityQuery = mediaQuery.identitiesQuery;
  const detailQuery = mediaQuery.detailQuery;
  const bulkDescribe = useBulkDescribe();
  const selectedMediaIds = Object.entries(selection)
    .filter(([, selected]) => selected)
    .map(([id]) => Number(id))
    .filter((id) => Number.isFinite(id) && id > 0);
  const describeProgress = bulkDescribe.progress;
  const activeDescribeRunId = bulkDescribe.runId;
  // Run started and still making progress: a polling error does NOT count as an
  // active run, so the primary CTA is never left permanently disabled (FE-02).
  const isDescribeRunning =
    bulkDescribe.submit.isPending ||
    (activeDescribeRunId !== null && !describeProgress.isTerminal && !describeProgress.isError);
  // The result panel stays visible through the terminal state so the operator
  // sees the outcome, until they explicitly dismiss that run (FE-01).
  const [dismissedRunId, setDismissedRunId] = useState<string | null>(null);
  const hasDescribeActivity = bulkDescribe.submit.isPending || activeDescribeRunId !== null;
  const isDescribePanelVisible =
    hasDescribeActivity && (activeDescribeRunId === null || dismissedRunId !== activeDescribeRunId);

  const onToggleAll = (checked: boolean) => toggleAll(items, checked);
  const onToggleRow = (item: WorkbenchMediaItem, checked: boolean) => toggleRow(item, checked);
  const detailStatusMessage = detailQuery.isLoading
    ? __('Loading media details…', 'alt-context')
    : detailQuery.isError
      ? __('Unable to load media details.', 'alt-context')
      : null;
  const identityStatusMessage = identityQuery.isLoading
    ? __('Loading identity data…', 'alt-context')
    : identityQuery.isError
      ? __('Unable to load identity data.', 'alt-context')
      : null;

  if (collapsed) {
    return <MediaSummaryBar onExpand={onExpand ?? (() => undefined)} />;
  }

  return (
    <>
      <div className="acx-media-selection">
        <MediaSelectionToolbar
          searchQuery={searchQuery}
          onSearchChange={onSearchChange}
          statusFilter={statusFilter}
          onStatusFilterChange={onStatusFilterChange}
          statusMessage={statusMessage}
          isError={isError}
          onRetry={onRetry}
        />

        <table className="acx-media-selection__table">
          <thead>
            <tr>
              <th scope="col">
                <Checkbox
                  ariaLabel={__('Select all items on this page', 'alt-context')}
                  checked={areAllPageRowsChecked}
                  onCheckedChange={(checked: boolean) => onToggleAll(checked)}
                  disabled={items.length === 0}
                />
              </th>
              <th scope="col">{__('Preview', 'alt-context')}</th>
              <th scope="col">{__('Details', 'alt-context')}</th>
              <th scope="col">{__('Tags', 'alt-context')}</th>
            </tr>
          </thead>
          <tbody>
            <MediaSelectionTableBody
              items={items}
              isLoading={isLoading}
              detailIsLoading={detailQuery.isPending || detailQuery.isFetching}
              onToggleRow={onToggleRow}
              selection={selection}
              identitiesDataSource={identityQuery.data?.data_source}
              onRetryIdentities={() => void identityQuery.refetch()}
            />
          </tbody>
        </table>

        <div className="acx-media-selection__footer">
          <MediaSelectionPagination
            currentPage={currentPage}
            totalPages={totalPages}
            perPage={perPage}
            onPerPageChange={onPerPageChange}
            onPageChange={onPageChange}
            labelId="acx-media-page-size-label"
          />
          <BulkDescribeCta
            selectedCount={selectedMediaIds.length}
            isSubmitting={bulkDescribe.submit.isPending}
            isCancelling={bulkDescribe.cancel.isPending}
            isRunning={isDescribeRunning}
            runId={activeDescribeRunId}
            progress={describeProgress}
            isPanelVisible={isDescribePanelVisible}
            errorMessage={bulkDescribe.submit.error?.message ?? bulkDescribe.cancel.error?.message ?? null}
            remoteActionDisabled={remoteGate.disabled}
            remoteActionTitle={remoteGate.title}
            remoteActionAriaDisabled={remoteGate['aria-disabled']}
            onSubmit={() => {
              if (offline) {
                return;
              }
              setDismissedRunId(null);
              bulkDescribe.submit.mutate(selectedMediaIds);
            }}
            onCancel={() => {
              if (activeDescribeRunId) {
                bulkDescribe.cancel.mutate(activeDescribeRunId);
              }
            }}
            onDismiss={() => setDismissedRunId(activeDescribeRunId)}
            onRetryPolling={() => describeProgress.retry()}
          />
          <MediaAnalyzeCta />
        </div>
      </div>
      {detailStatusMessage && (
        <div className="acx-identity-status">
          <span>{detailStatusMessage}</span>
          {detailQuery.isError && (
            <button type="button" className="acx-identity-status__retry" onClick={() => void detailQuery.refetch()}>
              {__('Retry', 'alt-context')}
            </button>
          )}
        </div>
      )}
      {identityStatusMessage && (
        <div className="acx-identity-status">
          <span>{identityStatusMessage}</span>
          {identityQuery.isError && (
            <button type="button" className="acx-identity-status__retry" onClick={() => void identityQuery.refetch()}>
              {__('Retry', 'alt-context')}
            </button>
          )}
        </div>
      )}
    </>
  );
};

interface MediaSelectionToolbarProps {
  searchQuery: string;
  onSearchChange: (event: ChangeEvent<HTMLInputElement>) => void;
  statusFilter: WorkbenchMediaStatus;
  onStatusFilterChange: (status: WorkbenchMediaStatus) => void;
  statusMessage: string;
  isError: boolean;
  onRetry?: () => void;
}

const MediaSelectionToolbar = ({
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  statusMessage,
  isError,
  onRetry,
}: MediaSelectionToolbarProps) => (
  <div className="acx-media-selection__toolbar">
    <label htmlFor="acx-media-search" className="acx-media-selection__search-label">
      {__('Search media', 'alt-context')}
    </label>
    <input
      id="acx-media-search"
      className="acx-media-selection__search"
      type="search"
      placeholder={__('Filter by alt text or tag…', 'alt-context')}
      value={searchQuery}
      onChange={onSearchChange}
    />
    <div className="acx-media-selection__status-filter">
      <span id="acx-media-status-label">{__('Status', 'alt-context')}</span>
      <Select.Root value={statusFilter} onValueChange={(value) => onStatusFilterChange(value as WorkbenchMediaStatus)}>
        <Select.Trigger className="acx-media-selection__status-filter-trigger" aria-labelledby="acx-media-status-label">
          <Select.Value />
          <Select.Icon className="acx-media-selection__status-filter-icon">
            <ChevronDown aria-hidden="true" size={16} />
          </Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Content className="acx-media-selection__status-filter-content" position="popper" sideOffset={6}>
            <Select.Viewport className="acx-media-selection__status-filter-viewport">
              <Select.Item value="all" className="acx-media-selection__status-filter-item">
                <Select.ItemText>{__('All media', 'alt-context')}</Select.ItemText>
                <Select.ItemIndicator className="acx-media-selection__status-filter-indicator">
                  <Check aria-hidden="true" size={14} />
                </Select.ItemIndicator>
              </Select.Item>
              <Select.Item value="missing" className="acx-media-selection__status-filter-item">
                <Select.ItemText>{__('Missing alt text', 'alt-context')}</Select.ItemText>
                <Select.ItemIndicator className="acx-media-selection__status-filter-indicator">
                  <Check aria-hidden="true" size={14} />
                </Select.ItemIndicator>
              </Select.Item>
            </Select.Viewport>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </div>

    <div className="acx-media-selection__toolbar-actions">
      <span className="acx-media-selection__status">{statusMessage}</span>
      {isError && onRetry && (
        <button type="button" className="acx-media-selection__retry" onClick={onRetry}>
          {__('Retry', 'alt-context')}
        </button>
      )}
    </div>
  </div>
);

interface BulkDescribeCtaProps {
  selectedCount: number;
  isSubmitting: boolean;
  isCancelling: boolean;
  isRunning: boolean;
  runId: string | null;
  progress: DescribeRunProgress;
  isPanelVisible: boolean;
  errorMessage: string | null;
  /** Remote-compute offline gate (RES-15) — never applied to cancel. */
  remoteActionDisabled?: boolean;
  remoteActionTitle?: string;
  remoteActionAriaDisabled?: true;
  onSubmit: () => void;
  onCancel: () => void;
  onDismiss: () => void;
  onRetryPolling: () => void;
}

/** Exported for unit tests of the presentational submit gate. */
export const BulkDescribeCta = ({
  selectedCount,
  isSubmitting,
  isCancelling,
  isRunning,
  runId,
  progress,
  isPanelVisible,
  errorMessage,
  remoteActionDisabled = false,
  remoteActionTitle,
  remoteActionAriaDisabled,
  onSubmit,
  onCancel,
  onDismiss,
  onRetryPolling,
}: BulkDescribeCtaProps) => {
  const canCancel = isRunning && runId !== null && !progress.isTerminal && !progress.isError;
  // Cannot cancel an errored/finished run — offer to clear the panel instead so a
  // new run can start from the terminal state (FE-01, rg-003).
  const canDismiss = isPanelVisible && (progress.isTerminal || progress.isError);

  return (
    <div className="acx-media-selection__bulk-describe">
      <div className="acx-media-selection__bulk-describe-actions">
        <button
          type="button"
          className="button"
          disabled={selectedCount === 0 || isSubmitting || isRunning || remoteActionDisabled}
          aria-disabled={remoteActionAriaDisabled}
          title={remoteActionTitle}
          onClick={onSubmit}
        >
          {isSubmitting ? SYNC_VOCABULARY.describeStarting : __('Describe selected', 'alt-context')}
        </button>
        {canCancel ? (
          <button type="button" className="button button-link" disabled={isCancelling} onClick={onCancel}>
            {isCancelling ? __('Cancelling…', 'alt-context') : __('Cancel describe run', 'alt-context')}
          </button>
        ) : null}
        {canDismiss ? (
          <button type="button" className="button button-link" onClick={onDismiss}>
            {__('Dismiss', 'alt-context')}
          </button>
        ) : null}
        <BulkDescribeReviewLink
          runId={runId}
          isTerminal={progress.isTerminal}
          appliedCount={progress.run ? progress.run.completed : 0}
        />
      </div>
      {isPanelVisible ? <BulkDescribeProgress progress={progress} onRetry={onRetryPolling} /> : null}
      {errorMessage ? <span className="acx-media-selection__bulk-describe-error">{errorMessage}</span> : null}
    </div>
  );
};

interface DescribeRunStatusMeta {
  label: string;
  Icon: typeof Clock;
  tone: 'pending' | 'running' | 'success' | 'warning' | 'danger' | 'muted';
  spin?: boolean;
}

const describeRunStatusMeta = (status: DescribeRunStatus): DescribeRunStatusMeta => {
  switch (status) {
    case DESCRIBE_RUN_STATUS.PENDING:
      return { label: SYNC_VOCABULARY.describeQueued, Icon: Clock, tone: 'pending' };
    case DESCRIBE_RUN_STATUS.RUNNING:
      return { label: SYNC_VOCABULARY.describeRunning, Icon: Loader2, tone: 'running', spin: true };
    case DESCRIBE_RUN_STATUS.COMPLETED:
      return { label: SYNC_VOCABULARY.describeCompleted, Icon: CheckCircle2, tone: 'success' };
    case DESCRIBE_RUN_STATUS.COMPLETED_WITH_ERRORS:
      return { label: SYNC_VOCABULARY.describeCompletedWithErrors, Icon: AlertTriangle, tone: 'warning' };
    case DESCRIBE_RUN_STATUS.FAILED:
      return { label: SYNC_VOCABULARY.describeFailed, Icon: XCircle, tone: 'danger' };
    case DESCRIBE_RUN_STATUS.CANCELLED:
      return { label: SYNC_VOCABULARY.describeCancelled, Icon: XCircle, tone: 'muted' };
    default: {
      // Exhaustiveness guard: a new status must be handled above.
      const unreachable: never = status;
      return unreachable;
    }
  }
};

const formatEtaLabel = (etaSeconds: number | null): string => {
  if (etaSeconds === null) {
    return __('calculating…', 'alt-context');
  }
  const total = Math.max(0, Math.round(etaSeconds));
  if (total < 60) {
    return sprintf(__('~%ds remaining', 'alt-context'), total);
  }
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return sprintf(__('~%1$dm %2$ds remaining', 'alt-context'), minutes, seconds);
};

const BulkDescribeProgress = ({
  progress,
  onRetry,
}: {
  progress: DescribeRunProgress;
  onRetry: () => void;
}) => {
  const { run, status, progressFraction, etaSeconds, stalledForSeconds, isTerminal, isError } = progress;

  if (isError) {
    return (
      <div className="acx-media-selection__bulk-describe-progress" role="alert" aria-live="assertive">
        <span className="acx-media-selection__bulk-describe-status acx-media-selection__bulk-describe-status--danger">
          <AlertTriangle aria-hidden="true" size={16} />
          {SYNC_VOCABULARY.describeLost}
        </span>
        <div className="acx-media-selection__bulk-describe-meta">
          <span>{__('Progress updates paused. Retry to resume.', 'alt-context')}</span>
          <button type="button" className="button button-link" onClick={onRetry}>
            {__('Retry', 'alt-context')}
          </button>
        </div>
      </div>
    );
  }

  if (run === null || status === null) {
    return (
      <div className="acx-media-selection__bulk-describe-progress" role="status" aria-live="polite">
        <span className="acx-media-selection__bulk-describe-status acx-media-selection__bulk-describe-status--running">
          <Loader2 className="acx-media-selection__bulk-describe-spin" aria-hidden="true" size={16} />
          {SYNC_VOCABULARY.describeStarting}
        </span>
      </div>
    );
  }

  const meta = describeRunStatusMeta(status);
  const percent = progressFraction === null ? null : Math.round(progressFraction * 100);
  // Processed = every terminal item (completed + failed + skipped) so the bar
  // and count reflect true progress, not just successes.
  const processed = run.completed + run.failed + run.skipped;
  const countsLabel = sprintf(
    __('%1$d of %2$d processed', 'alt-context'),
    processed,
    run.total,
  );

  return (
    <div className="acx-media-selection__bulk-describe-progress" role="status" aria-live="polite">
      <span
        className={`acx-media-selection__bulk-describe-status acx-media-selection__bulk-describe-status--${meta.tone}`}
      >
        <meta.Icon
          className={meta.spin ? 'acx-media-selection__bulk-describe-spin' : undefined}
          aria-hidden="true"
          size={16}
        />
        {meta.label}
      </span>
      <progress
        className="acx-media-selection__bulk-describe-bar"
        max={run.total > 0 ? run.total : 1}
        value={processed}
        aria-label={countsLabel}
      />
      <div className="acx-media-selection__bulk-describe-meta">
        <span>
          {countsLabel}
          {percent !== null ? ` (${percent}%)` : ''}
        </span>
        {run.failed > 0 ? (
          <span className="acx-media-selection__bulk-describe-failed">
            {sprintf(__('%d failed', 'alt-context'), run.failed)}
          </span>
        ) : null}
        {run.skipped > 0 ? (
          <span className="acx-media-selection__bulk-describe-skipped">
            {sprintf(__('%d skipped', 'alt-context'), run.skipped)}
          </span>
        ) : null}
        {!isTerminal ? (
          <span className="acx-media-selection__bulk-describe-eta">{formatEtaLabel(etaSeconds)}</span>
        ) : null}
      </div>
      {stalledForSeconds !== null ? (
        <span className="acx-media-selection__bulk-describe-stall">
          <AlertTriangle aria-hidden="true" size={16} />
          {sprintf(
            __('No progress for %ds — the run may be stalled.', 'alt-context'),
            stalledForSeconds,
          )}
        </span>
      ) : null}
    </div>
  );
};

interface MediaSelectionPaginationProps {
  currentPage: number;
  totalPages: number;
  perPage: number;
  onPerPageChange: (perPage: number) => void;
  onPageChange: (page: number) => void;
  labelId: string;
}

const MEDIA_PAGE_SIZES = [10, 50, 100] as const;

const MediaSelectionPagination = ({
  currentPage,
  totalPages,
  perPage,
  onPerPageChange,
  onPageChange,
  labelId,
}: MediaSelectionPaginationProps) => {
  const boundedTotalPages = Math.max(1, totalPages);
  const boundedCurrentPage = Math.min(Math.max(1, currentPage), boundedTotalPages);

  const handlePerPageChange = (value: string) => {
    const selected = Number(value);
    if (!Number.isFinite(selected)) {
      return;
    }
    onPerPageChange(selected);
  };

  return (
    <div
      className="acx-media-selection__pagination"
      role="navigation"
      aria-label={__('Media pagination', 'alt-context')}
    >
      <button
        type="button"
        onClick={() => onPageChange(Math.max(1, boundedCurrentPage - 1))}
        disabled={boundedCurrentPage <= 1}
      >
        {__('Previous', 'alt-context')}
      </button>
      <span>
        {__('Page', 'alt-context')} {boundedCurrentPage} {__('of', 'alt-context')} {boundedTotalPages}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(Math.min(boundedTotalPages, boundedCurrentPage + 1))}
        disabled={boundedCurrentPage >= boundedTotalPages}
      >
        {__('Next', 'alt-context')}
      </button>
      <div className="acx-media-selection__page-size">
        <span id={labelId}>{__('Images per page', 'alt-context')}</span>
        <Select.Root value={String(perPage)} onValueChange={handlePerPageChange}>
          <Select.Trigger className="acx-media-selection__page-size-trigger" aria-labelledby={labelId}>
            <Select.Value />
            <Select.Icon className="acx-media-selection__page-size-icon">
              <ChevronDown aria-hidden="true" size={16} />
            </Select.Icon>
          </Select.Trigger>
          <Select.Portal>
            <Select.Content className="acx-media-selection__page-size-content" position="popper" sideOffset={6}>
              <Select.Viewport className="acx-media-selection__page-size-viewport">
                {MEDIA_PAGE_SIZES.map((size) => (
                  <Select.Item key={size} value={String(size)} className="acx-media-selection__page-size-item">
                    <Select.ItemText>{size}</Select.ItemText>
                    <Select.ItemIndicator className="acx-media-selection__page-size-indicator">
                      <Check aria-hidden="true" size={14} />
                    </Select.ItemIndicator>
                  </Select.Item>
                ))}
              </Select.Viewport>
            </Select.Content>
          </Select.Portal>
        </Select.Root>
      </div>
    </div>
  );
};

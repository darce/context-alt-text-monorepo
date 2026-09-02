import { ChangeEvent, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as Select from '@radix-ui/react-select';
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Clock, Loader2, XCircle } from 'lucide-react';
import { __, _n, sprintf } from '@wordpress/i18n';
import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { WorkbenchMediaStatus } from '../../api/workbenchMediaApi';
import { fetchSettings, type SettingsResponse } from '../../api/settingsApi';
import { toSettings } from '../../navigation/appLinks';
import { MediaSelectionTableBody } from './MediaSelectionTableBody';
import { MediaAnalyzeCta } from './MediaAnalyzeCta';
import { BulkDescribeReviewLink } from './BulkDescribeReviewLink';

import { Checkbox } from '../../../components/ui/checkbox';
import { useBulkDescribe } from '../../hooks/useBulkDescribe';
import type { DescribeRunProgress } from '../../hooks/useDescribeRunProgress';
import { useRecognitionCooldown } from '../../hooks/useRecognitionCooldown';
import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import { DESCRIBE_RUN_STATUS, type DescribeRunStatus } from '../../api/describeApi';
import { isCooldownSignal } from '../../utils/retryPolicy';
import { formatUserFacingError, isAuthExpiredError } from '../../utils/userFacingError';
import { UserFacingErrorNotice } from '../../components/ui/UserFacingErrorNotice';
import { useWorkbenchMediaContext } from './WorkbenchMediaContext';
import { SYNC_VOCABULARY } from './syncPresentation';
import { ACCENT_PRIMARY_ATTR, FOOTER_ACCENT_OWNER, selectMediaFooterCtaState } from './mediaFooterCtaState';
import { deriveIdentitiesPresentationSource } from './deriveIdentitiesPresentationSource';

interface MediaSelectionProps {
  /**
   * §7: a review card / label / review panel primary is on screen. When true the
   * card owns the single viewport accent primary, so both footer CTAs step down.
   */
  reviewActive?: boolean;
}

export const MediaSelection = ({ reviewActive = false }: MediaSelectionProps): React.JSX.Element => {
  const { selection: mediaSelection, filters, mediaQueue } = useWorkbenchMediaContext();
  // RES-15: container owns offline signal; BulkDescribeCta is pure presentational.
  const offline = useSyncOffline();
  const remoteGate = useRemoteActionGate(offline);
  const { selection, toggleRow, toggleAll } = mediaSelection;
  const {
    searchQuery,
    handleSearchChange: onSearchChange,
    clearSearch,
    statusFilter,
    handleStatusChange: onStatusFilterChange,
    currentPage,
    perPage,
    setPerPage: onPerPageChange,
    setCurrentPage: onPageChange,
  } = filters;
  const { mediaQuery, statusMessage, isStatusPending } = mediaQueue;

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
  // L1 settings query: share SettingsPage's ['settings'] key so a save updates this footer.
  const settingsQuery = useQuery<SettingsResponse>({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    retry: false,
  });
  const recognitionEnabled = settingsQuery.data?.recognition_enabled;
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
    : detailQuery.isError && !isAuthExpiredError(detailQuery.error)
      ? formatUserFacingError(detailQuery.error, __('Unable to load media details.', 'alt-context'))
      : null;
  const identityStatusMessage = identityQuery.isLoading
    ? __('Loading identity data…', 'alt-context')
    : identityQuery.isError && !isAuthExpiredError(identityQuery.error)
      ? formatUserFacingError(identityQuery.error, __('Unable to load identity data.', 'alt-context'))
      : null;
  const detailAuthExpired = detailQuery.isError && isAuthExpiredError(detailQuery.error);
  const identityAuthExpired = identityQuery.isError && isAuthExpiredError(identityQuery.error);

  // §7 media-footer CTA hierarchy: a per-state selector resolves the SINGLE
  // accent primary across the footer, reconciled against the review card.
  const footerCta = selectMediaFooterCtaState({ reviewActive, describeRunning: isDescribeRunning });

  return (
    <>
      <div className="acx-media-selection">
        <MediaSelectionToolbar
          searchQuery={searchQuery}
          onSearchChange={onSearchChange}
          statusFilter={statusFilter}
          onStatusFilterChange={onStatusFilterChange}
          statusMessage={statusMessage}
          isStatusPending={isStatusPending}
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
              identitiesDataSource={deriveIdentitiesPresentationSource(
                identityQuery.isError,
                identityQuery.data,
              )}
              onRetryIdentities={() => void identityQuery.refetch()}
              searchQuery={searchQuery}
              statusFilter={statusFilter}
              onClearSearch={clearSearch}
              onClearStatusFilter={() => onStatusFilterChange('all')}
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
            errorMessage={bulkDescribe.errorMessage}
            remoteActionTitle={remoteGate.title}
            remoteActionAriaDisabled={remoteGate['aria-disabled']}
            accentPrimary={footerCta.accentOwner === FOOTER_ACCENT_OWNER.DESCRIBE}
            recognitionEnabled={recognitionEnabled}
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
          <MediaAnalyzeCta accentPrimary={footerCta.accentOwner === FOOTER_ACCENT_OWNER.ANALYZE} />
        </div>
      </div>
      {detailAuthExpired ? (
        <UserFacingErrorNotice
          className="acx-identity-status"
          error={detailQuery.error}
          fallback={__('Unable to load media details.', 'alt-context')}
        />
      ) : null}
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
      {identityAuthExpired ? (
        <UserFacingErrorNotice
          className="acx-identity-status"
          error={identityQuery.error}
          fallback={__('Unable to load identity data.', 'alt-context')}
        />
      ) : null}
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
  /**
   * True while the queue is still fetching. Suppresses the transient status from
   * the live region — gated on the context boolean, not display-copy equality
   * [B-01][A11Y-08][sr-007].
   */
  isStatusPending: boolean;
  isError: boolean;
  onRetry?: () => void;
}

/** Coalesce rapid settled-status changes (search keystroke storms) [B-01]. */
const TOOLBAR_STATUS_ANNOUNCE_DEBOUNCE_MS = 1000;

export const MediaSelectionToolbar = ({
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  statusMessage,
  isStatusPending,
  isError,
  onRetry,
}: MediaSelectionToolbarProps) => {
  // Settled candidate: exclude transient fetch-pending so fetch churn never
  // enters the live region. Visual span still shows the full message [B-01 option b].
  // Gate on isStatusPending (not translated display copy) [sr-007].
  const settledCandidate = isStatusPending ? null : statusMessage;

  // Always-mounted live region: start empty so the region exists before text
  // arrives (a status that mounts with content often is not announced).
  const [announcedStatus, setAnnouncedStatus] = useState('');

  useEffect(() => {
    if (settledCandidate === null) {
      return;
    }
    const timer = window.setTimeout(() => {
      setAnnouncedStatus(settledCandidate);
    }, TOOLBAR_STATUS_ANNOUNCE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [settledCandidate]);

  return (
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
        <span className="acx-media-selection__status">
          {/* Visual status — full message including transient Updating… */}
          <span aria-hidden="true">{statusMessage}</span>
          {/*
            Always-mounted polite region [B-01][A11Y-08]. Debounced settled text
            only — never "Updating media queue…". Per-correction success strings
            live on the row region, not here [B-02].
          */}
          <span
            role="status"
            aria-live="polite"
            className="screen-reader-text"
            data-testid="media-selection-toolbar-live-status"
          >
            {announcedStatus}
          </span>
        </span>
        {isStatusPending ? (
          <p data-testid="acx-zone-z-filters-loading">{__('Loading media…', 'alt-context')}</p>
        ) : null}
        {isError ? (
          <p role="alert" data-testid="acx-zone-z-filters-error">
            {__('Unable to load media.', 'alt-context')}
          </p>
        ) : null}
        {isError && onRetry && (
          <button type="button" className="acx-media-selection__retry" onClick={onRetry}>
            {__('Retry', 'alt-context')}
          </button>
        )}
      </div>
    </div>
  );
};

/** aria-describedby target for the §7 offline reason on the describe submit CTA. */
const DESCRIBE_OFFLINE_REASON_ID = 'acx-describe-offline-reason';
/** aria-describedby target for the HAI-05 recognition disclosure under the primary. */
const DESCRIBE_RECOGNITION_DISCLOSURE_ID = 'acx-describe-recognition-disclosure';

const joinDescribedBy = (...ids: (string | undefined)[]): string | undefined => {
  const joined = ids.filter((id): id is string => Boolean(id)).join(' ');
  return joined === '' ? undefined : joined;
};

interface BulkDescribeCtaProps {
  selectedCount: number;
  isSubmitting: boolean;
  isCancelling: boolean;
  isRunning: boolean;
  runId: string | null;
  progress: DescribeRunProgress;
  isPanelVisible: boolean;
  errorMessage: string | null;
  /**
   * Remote-compute offline gate (RES-15). §7: aria-disabled only (still focusable,
   * reason via aria-describedby) — never HTML `disabled`. Never applied to cancel.
   */
  remoteActionTitle?: string;
  remoteActionAriaDisabled?: true;
  /** §7 accent ownership: mark the describe surface as the single accent primary. */
  accentPrimary?: boolean;
  /**
   * GET /acx/v1/settings `recognition_enabled`. `undefined` while loading/unknown
   * draws the OFF wording without a Settings link (RLSE-04).
   */
  recognitionEnabled?: boolean;
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
  remoteActionTitle,
  remoteActionAriaDisabled,
  accentPrimary = false,
  recognitionEnabled,
  onSubmit,
  onCancel,
  onDismiss,
  onRetryPolling,
}: BulkDescribeCtaProps) => {
  const canCancel = isRunning && runId !== null && !progress.isTerminal && !progress.isError;
  // Cannot cancel an errored/finished run — offer to clear the panel instead so a
  // new run can start from the terminal state (FE-01, rg-003).
  const canDismiss = isPanelVisible && (progress.isTerminal || progress.isError);
  const offlineGated = Boolean(remoteActionAriaDisabled);
  const recognitionKnownOn = recognitionEnabled === true;
  const describeDescribedBy = joinDescribedBy(
    DESCRIBE_RECOGNITION_DISCLOSURE_ID,
    offlineGated ? DESCRIBE_OFFLINE_REASON_ID : undefined,
  );

  return (
    <div className="acx-media-selection__bulk-describe">
      <div className="acx-media-selection__bulk-describe-actions">
        <button
          type="button"
          // BR-73: the accent marker + accent chrome live on the submit button (the
          // actually-accent-styled primary), never on the neutral wrapper div.
          className={accentPrimary ? 'button acx-accent-primary-action' : 'button'}
          // BR-74: offline never HTML-disables — the aria-describedby reason must stay
          // reachable on a focusable control. Offline is gated by aria-disabled + the
          // onClick guard; zero-selection/submitting/running still disable when online.
          disabled={!offlineGated && (selectedCount === 0 || isSubmitting || isRunning)}
          aria-disabled={remoteActionAriaDisabled}
          aria-describedby={describeDescribedBy}
          title={remoteActionTitle}
          onClick={() => {
            // BR-76: presentational offline guard mirrors MediaAnalyzeCta — activation is
            // a no-op while offline-gated (the container onSubmit also fail-fasts offline).
            if (offlineGated) {
              return;
            }
            onSubmit();
          }}
          {...(accentPrimary ? { [ACCENT_PRIMARY_ATTR]: true } : {})}
        >
          {isSubmitting
            ? SYNC_VOCABULARY.describeStarting
            : selectedCount > 0
              ? sprintf(_n('Describe %d selected', 'Describe %d selected', selectedCount, 'alt-context'), selectedCount)
              : __('Describe selected', 'alt-context')}
        </button>
        {offlineGated && remoteActionTitle ? (
          <span id={DESCRIBE_OFFLINE_REASON_ID} className="screen-reader-text">
            {remoteActionTitle}
          </span>
        ) : null}
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
      <p id={DESCRIBE_RECOGNITION_DISCLOSURE_ID} className="acx-media-selection__bulk-describe-disclosure">
        {recognitionKnownOn ? (
          <>
            {sprintf(
              __('Identifies people first (AI) · ~%d credits · Turn off in', 'alt-context'),
              selectedCount,
            )}{' '}
            <a href={toSettings()}>{__('Settings', 'alt-context')}</a>
          </>
        ) : (
          sprintf(__('People are not identified (recognition off) · ~%d credits', 'alt-context'), selectedCount)
        )}
      </p>
      {isPanelVisible ? <BulkDescribeProgress progress={progress} onRetry={onRetryPolling} /> : null}
      {errorMessage ? (
        // [A11Y-21][A11Y-24][sr-004]: error is text + role=alert, never colour alone.
        <div className="acx-media-selection__bulk-describe-error" role="alert">
          {errorMessage}
        </div>
      ) : null}
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

export const BulkDescribeProgress = ({ progress, onRetry }: { progress: DescribeRunProgress; onRetry: () => void }) => {
  const { run, status, progressFraction, etaSeconds, stalledForSeconds, isTerminal, isError, isFrozen } = progress;
  const cooldown = useRecognitionCooldown();

  // A hard error whose cause IS the armed cooldown (429/503-with-Retry-After)
  // is the same signal as the waiting state, not a dead run: prefer the calm
  // paused notice over the assertive role=alert Retry so the two breakers don't
  // shout past each other (BR review). A non-cooldown hard error still alerts.
  const errorIsArmedCooldown = isError && cooldown.isCoolingDown && isCooldownSignal(progress.error);
  const hardError = isError && !errorIsArmedCooldown;

  // Frozen surface is a designed state (RLSE-04): a transient poll timeout
  // (BR-07), the shared recognition cooldown, or a cooldown-caused hard error
  // pauses updates, so say so — otherwise a stopped bar reads as a hang and
  // invites the reload traffic the cooldown exists to prevent. Announced by the
  // surrounding polite live region (A11Y-21); icon paired with color (sr-004).
  //
  // The announced sentence is static so the polite region does not re-announce
  // every second (A11Y-21); the ticking countdown lives in an aria-hidden span
  // — visible, never re-read by a screen reader.
  const isWaiting = !isTerminal && !hardError && (isFrozen || cooldown.isCoolingDown);
  const waitingNotice = isWaiting ? (
    <span className="acx-media-selection__bulk-describe-paused">
      <Clock aria-hidden="true" size={16} />
      <span className="acx-media-selection__bulk-describe-paused-label">
        {__('Waiting for the service — progress updates paused.', 'alt-context')}
      </span>
      {cooldown.isCoolingDown && cooldown.remainingSeconds > 0 ? (
        <span className="acx-media-selection__bulk-describe-countdown" aria-hidden="true">
          {sprintf(__('Retrying in %ds.', 'alt-context'), cooldown.remainingSeconds)}
        </span>
      ) : null}
    </span>
  ) : null;

  if (hardError) {
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
        {waitingNotice}
      </div>
    );
  }

  const meta = describeRunStatusMeta(status);
  const percent = progressFraction === null ? null : Math.round(progressFraction * 100);
  // Processed = every terminal item (completed + failed + skipped) so the bar
  // and count reflect true progress, not just successes.
  const processed = run.completed + run.failed + run.skipped;
  const countsLabel = sprintf(__('%1$d of %2$d processed', 'alt-context'), processed, run.total);

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
      {waitingNotice}
      {stalledForSeconds !== null ? (
        <span className="acx-media-selection__bulk-describe-stall">
          <AlertTriangle aria-hidden="true" size={16} />
          {sprintf(__('No progress for %ds — the run may be stalled.', 'alt-context'), stalledForSeconds)}
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

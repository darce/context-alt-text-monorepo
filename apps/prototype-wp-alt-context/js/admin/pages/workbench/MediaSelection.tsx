import { ChangeEvent, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as Select from '@radix-ui/react-select';
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  CircleStop,
  Clock,
  Flame,
  Loader2,
  Zap,
  XCircle,
} from 'lucide-react';
import { __, _n, sprintf } from '@wordpress/i18n';
import type { WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { WorkbenchMediaStatus } from '../../api/workbenchMediaApi';
import { fetchSettings, type SettingsResponse } from '../../api/settingsApi';
import { toSettings } from '../../navigation/appLinks';
import { MediaSelectionTableBody } from './MediaSelectionTableBody';
import { BulkDescribeReviewLink } from './BulkDescribeReviewLink';
import { useJobPipeline } from './JobPipelineContext';

import { Checkbox } from '../../../components/ui/checkbox';
import { useBulkDescribe } from '../../hooks/useBulkDescribe';
import { setDescribeProgressMounted } from '../../hooks/activeDescribeRun';
import type { DescribeRunProgress } from '../../hooks/useDescribeRunProgress';
import { useRecognitionCooldown } from '../../hooks/useRecognitionCooldown';
import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import {
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  GPU_STATE,
  type DescribeRunStatus,
  type GpuState,
} from '../../api/describeApi';
import { toDescriptionHistoryRun } from '../../navigation/appLinks';
import { isCooldownSignal } from '../../utils/retryPolicy';
import { formatUserFacingError, isAuthExpiredError } from '../../utils/userFacingError';
import { UserFacingErrorNotice } from '../../components/ui/UserFacingErrorNotice';
import { useWorkbenchMediaContext } from './WorkbenchMediaContext';
import { SYNC_VOCABULARY } from './syncPresentation';
import { ACCENT_PRIMARY_ATTR, FOOTER_ACCENT_OWNER, selectMediaFooterCtaState } from './mediaFooterCtaState';
import { deriveIdentitiesPresentationSource } from './deriveIdentitiesPresentationSource';
import {
  GPU_STATE_ICON,
  GPU_STATE_TONE,
  GPU_STATE_VOCABULARY,
  gpuStateNotice,
  gpuStatePresentation,
  type GpuStateIcon,
  type GpuStateTone,
} from './gpuStatePresentation';

interface MediaSelectionProps {
  /**
   * §7: a review card / label / review panel primary is on screen. When true the
   * card owns the single viewport accent primary, so the footer Describe CTA steps down.
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
  const pipeline = useJobPipeline();
  const [identify, setIdentify] = useState<{ pending: boolean; error: string | null }>({ pending: false, error: null });
  const startDescribe = (ids: number[]) => {
    setDismissedRunId(null);
    bulkDescribe.submit.mutate(ids);
  };
  // L1 settings query: share SettingsPage's ['settings'] key so a save updates this footer.
  const settingsQuery = useQuery<SettingsResponse>({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    retry: false,
  });
  const recognitionEnabled = settingsQuery.data?.recognition_enabled;
  const recognitionPolicyKnown = typeof recognitionEnabled === 'boolean';
  const isSettingsPending = !recognitionPolicyKnown;
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
            errorMessage={identify.error ?? bulkDescribe.errorMessage}
            remoteActionTitle={remoteGate.title}
            remoteActionAriaDisabled={remoteGate['aria-disabled']}
            accentPrimary={footerCta.accentOwner === FOOTER_ACCENT_OWNER.DESCRIBE}
            recognitionEnabled={recognitionEnabled}
            isIdentifying={identify.pending}
            isSettingsPending={isSettingsPending}
            onSubmit={() => {
              if (offline || identify.pending) return;
              if (!recognitionPolicyKnown || selectedMediaIds.length === 0) return;
              const ids = selectedMediaIds;
              if (recognitionEnabled !== true) {
                startDescribe(ids);
                return;
              }
              setIdentify({ pending: true, error: null });
              void pipeline.scanAndWait(ids).then(
                () => {
                  setIdentify({ pending: false, error: null });
                  startDescribe(ids);
                },
                (error: unknown) => {
                  const message =
                    error instanceof Error && error.message
                      ? error.message
                      : __('People identification failed. Nothing was described.', 'alt-context');
                  setIdentify({ pending: false, error: message });
                },
              );
            }}
            onCancel={() => {
              if (identify.pending) {
                pipeline.cancelScan(pipeline.history.activeJobIds);
                return;
              }
              if (activeDescribeRunId) {
                bulkDescribe.cancel.mutate(activeDescribeRunId);
              }
            }}
            onDismiss={() => setDismissedRunId(activeDescribeRunId)}
            onRetryPolling={() => describeProgress.retry()}
          />
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
/** aria-describedby target for the zero-selection hold reason on the describe submit CTA. */
const DESCRIBE_EMPTY_SELECTION_REASON_ID = 'acx-describe-empty-selection-reason';
/** aria-describedby target for the HAI-05 recognition disclosure under the primary. */
const DESCRIBE_RECOGNITION_DISCLOSURE_ID = 'acx-describe-recognition-disclosure';

/** Join the reason ids that currently apply; `undefined` when none do. */
const joinDescribedBy = (...ids: (string | undefined)[]): string | undefined => {
  const present = ids.filter((id): id is string => typeof id === 'string' && id.length > 0);
  return present.length > 0 ? present.join(' ') : undefined;
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
   * holds the primary and does not claim recognition is off (HAI-05 / FORM-04).
   */
  recognitionEnabled?: boolean;
  isIdentifying: boolean;
  /** True while GET /settings has not produced a boolean policy. */
  isSettingsPending?: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  onDismiss: () => void;
  onReviewDrafts?: () => void;
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
  isIdentifying = false,
  isSettingsPending = false,
  onSubmit,
  onCancel,
  onDismiss,
  onReviewDrafts,
  onRetryPolling,
}: BulkDescribeCtaProps) => {
  const progressPhase = progress.run?.phase;
  const progressOwnsCancel =
    isPanelVisible &&
    (progressPhase === DESCRIBE_RUN_PHASE.QUEUED ||
      progressPhase === DESCRIBE_RUN_PHASE.WARMING ||
      progressPhase === DESCRIBE_RUN_PHASE.DESCRIBING);
  const canCancelDescribe =
    isRunning && runId !== null && !progress.isTerminal && !progress.isError && !progressOwnsCancel;
  // Identifying is a cancellable wait of its own: the footer owns Cancel while the
  // describe progress panel is not yet mounted to own it.
  const canCancel = isIdentifying || canCancelDescribe;
  // Cannot cancel an errored/finished run — offer to clear the panel instead so a
  // new run can start from the terminal state (FE-01, rg-003). Complete-phase
  // dismiss lives on the named done-state in BulkDescribeProgress.
  const canDismiss =
    isPanelVisible &&
    (progress.isTerminal || progress.isError) &&
    progress.run?.phase !== DESCRIBE_RUN_PHASE.COMPLETE;
  const offlineGated = Boolean(remoteActionAriaDisabled);
  // rg-003: an empty selection HOLDS the primary (aria-disabled + no-op click) but
  // never removes it from the tab order, so the control and its reason stay
  // discoverable from the zero state (A11Y-11 keyboard walk, A11Y-24 empty state).
  const emptySelectionHeld = selectedCount === 0;
  const recognitionKnownOn = recognitionEnabled === true;
  const recognitionKnownOff = recognitionEnabled === false;
  // In-flight identification and an unknown recognition policy hold the primary for
  // the same reason: acting now would either double-submit or act on an unknown policy.
  const submitHeld = offlineGated || emptySelectionHeld || isIdentifying || isSettingsPending;
  const gpuState = progress.gpuState ?? null;

  return (
    <div className="acx-media-selection__bulk-describe">
      <GpuTierStatus
        gpuState={gpuState}
        cpuDraftCount={progress.run?.completed ?? 0}
        isRunRelevant={runId !== null || isRunning}
      />
      <div className="acx-media-selection__bulk-describe-actions">
        <button
          type="button"
          // BR-73: the accent marker + accent chrome live on the submit button (the
          // actually-accent-styled primary), never on the neutral wrapper div.
          className={accentPrimary ? 'button acx-accent-primary-action' : 'button'}
          // BR-74 / rg-003: offline, identifying, settings-pending, and zero-selection
          // never HTML-disable — that drops the control from the tab order and strands
          // its aria-describedby reason on an unfocusable element. All are held by
          // aria-disabled + the onClick guard. In-flight submit/run still HTML-disable
          // when online (double-submit guard).
          disabled={!offlineGated && (isSubmitting || isRunning)}
          aria-disabled={submitHeld ? true : undefined}
          aria-describedby={joinDescribedBy(
            DESCRIBE_RECOGNITION_DISCLOSURE_ID,
            offlineGated ? DESCRIBE_OFFLINE_REASON_ID : undefined,
            emptySelectionHeld ? DESCRIBE_EMPTY_SELECTION_REASON_ID : undefined,
          )}
          title={remoteActionTitle}
          onClick={() => {
            // BR-76: presentational hold guard — activation is a no-op while held (the
            // container onSubmit also fail-fasts offline and while identifying).
            if (submitHeld) {
              return;
            }
            onSubmit();
          }}
          {...(accentPrimary ? { [ACCENT_PRIMARY_ATTR]: true } : {})}
        >
          {isIdentifying
            ? __('Identifying people…', 'alt-context')
            : isSettingsPending
              ? __('Loading settings…', 'alt-context')
              : isSubmitting
                ? SYNC_VOCABULARY.describeStarting
                : // A11Y-04 (2.5.3): the visible text IS the accessible name, so at zero
                  // selection it must not read "Describe 0 selected".
                  emptySelectionHeld
                  ? __('Describe selected', 'alt-context')
                  : sprintf(__('Describe %d selected', 'alt-context'), selectedCount)}
        </button>
        <span role="status" aria-live="polite" className="screen-reader-text">
          {isIdentifying ? __('Identifying people…', 'alt-context') : ''}
        </span>
        {offlineGated && remoteActionTitle ? (
          <span id={DESCRIBE_OFFLINE_REASON_ID} className="screen-reader-text">
            {remoteActionTitle}
          </span>
        ) : null}
        {emptySelectionHeld ? (
          <span id={DESCRIBE_EMPTY_SELECTION_REASON_ID} className="screen-reader-text">
            {__('Select at least one media item to describe.', 'alt-context')}
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
        {progress.run?.phase === DESCRIBE_RUN_PHASE.COMPLETE ? null : (
          <BulkDescribeReviewLink
            runId={runId}
            isTerminal={progress.isTerminal}
            appliedCount={progress.run ? progress.run.completed : 0}
          />
        )}
      </div>
      <p id={DESCRIBE_RECOGNITION_DISCLOSURE_ID} className="acx-media-selection__bulk-describe-disclosure">
        {recognitionKnownOn ? (
          <>
            {sprintf(__('Identifies people first (AI) · ~%d credits · Turn off in', 'alt-context'), selectedCount)}{' '}
            <a href={toSettings()}>{__('Settings', 'alt-context')}</a>
          </>
        ) : recognitionKnownOff ? (
          sprintf(__('People are not identified (recognition off) · ~%d credits', 'alt-context'), selectedCount)
        ) : (
          __('Checking recognition settings…', 'alt-context')
        )}
      </p>
      {isPanelVisible ? (
        <BulkDescribeProgress
          progress={progress}
          onRetry={onRetryPolling}
          onCancel={onCancel}
          onDismiss={onDismiss}
          onReviewDrafts={onReviewDrafts}
          isCancelling={isCancelling}
        />
      ) : null}
      {errorMessage ? (
        // [A11Y-21][A11Y-24][sr-004]: error is text + role=alert, never colour alone.
        <div className="acx-media-selection__bulk-describe-error" role="alert">
          {errorMessage}
        </div>
      ) : null}
    </div>
  );
};

const GPU_STATE_ICON_COMPONENT = {
  [GPU_STATE_ICON.HELP]: CircleHelp,
  [GPU_STATE_ICON.STOPPED]: CircleStop,
  [GPU_STATE_ICON.STARTING]: Loader2,
  [GPU_STATE_ICON.WARMING]: Flame,
  [GPU_STATE_ICON.READY]: Zap,
  [GPU_STATE_ICON.DEGRADED]: AlertTriangle,
} satisfies Record<GpuStateIcon, typeof Clock>;

const gpuStateToneClass = (tone: GpuStateTone): string => {
  switch (tone) {
    case GPU_STATE_TONE.SUCCESS:
      return ' acx-sync-status--success';
    case GPU_STATE_TONE.WARNING:
      return ' acx-sync-status--warning';
    case GPU_STATE_TONE.PENDING:
    case GPU_STATE_TONE.RUNNING:
      return ' acx-sync-status--info';
    case GPU_STATE_TONE.MUTED:
      return '';
  }
};

/** GPU tier never gates the primary action; it only reports tier consequences. */
export const GpuTierStatus = ({
  gpuState,
  cpuDraftCount,
  isRunRelevant = true,
}: {
  gpuState: GpuState | null;
  cpuDraftCount: number;
  /** Unknown telemetry is meaningful only while a describe run exists or starts. */
  isRunRelevant?: boolean;
}): React.JSX.Element | null => {
  if (!isRunRelevant) {
    return null;
  }

  // Keep the live region mounted for every state of a relevant run. Null is a
  // legacy direct-call input; the hook otherwise normalizes missing, malformed,
  // and stale telemetry to UNKNOWN before it reaches this boundary.
  const displayedState: GpuState = (() => {
    switch (gpuState) {
      case null:
      case GPU_STATE.UNKNOWN:
        return GPU_STATE.UNKNOWN;
      case GPU_STATE.STOPPED:
      case GPU_STATE.STARTING:
      case GPU_STATE.WARMING:
      case GPU_STATE.READY:
      case GPU_STATE.DEGRADED:
        return gpuState;
      default: {
        const unreachable: never = gpuState;
        return unreachable;
      }
    }
  })();

  const presentation = gpuStatePresentation(displayedState);
  const Icon = GPU_STATE_ICON_COMPONENT[presentation.icon];
  const spin = presentation.icon === GPU_STATE_ICON.STARTING;
  const accessibleName = `${GPU_STATE_VOCABULARY.tierPrefix} ${presentation.label}`;

  return (
    <div
      className={`acx-sync-status acx-media-selection__gpu-tier-status${gpuStateToneClass(presentation.tone)}`}
      role="status"
      aria-label={accessibleName}
      aria-live="polite"
      aria-atomic="true"
      data-gpu-state={displayedState}
      data-gpu-terminal={presentation.terminal}
    >
      <span className="acx-media-selection__detail-chip">
        <Icon className={spin ? 'acx-media-selection__bulk-describe-spin' : undefined} aria-hidden="true" size={16} />
        {GPU_STATE_VOCABULARY.tierPrefix} {presentation.label}
      </span>
      <span className="acx-sync-status__label">{gpuStateNotice(displayedState, cpuDraftCount)}</span>
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

export const BulkDescribeProgress = ({
  progress,
  onRetry,
  onCancel,
  onDismiss,
  isCancelling = false,
}: {
  progress: DescribeRunProgress;
  onRetry: () => void;
  onCancel?: () => void;
  onDismiss?: () => void;
  /** Accepted so a no-op mutant cannot replace the history-link effector (WBUX-6 F1). */
  onReviewDrafts?: () => void;
  isCancelling?: boolean;
}) => {
  const { run, status, progressFraction, etaSeconds, stalledForSeconds, isTerminal, isError, isFrozen } = progress;
  const cooldown = useRecognitionCooldown();

  useEffect(() => {
    setDescribeProgressMounted(true);
    return () => setDescribeProgressMounted(false);
  }, []);

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

  const cancelControl =
    onCancel && !isTerminal ? (
      <button type="button" className="button button-link" disabled={isCancelling} onClick={onCancel}>
        {isCancelling ? __('Cancelling…', 'alt-context') : __('Cancel describe run', 'alt-context')}
      </button>
    ) : null;

  if (run.phase === DESCRIBE_RUN_PHASE.QUEUED) {
    return (
      <div className="acx-media-selection__bulk-describe-progress" role="status" aria-live="polite">
        <span className="acx-media-selection__bulk-describe-status acx-media-selection__bulk-describe-status--pending">
          <Clock aria-hidden="true" size={16} />
          {__('Queued…', 'alt-context')}
        </span>
        {cancelControl}
        {waitingNotice}
      </div>
    );
  }

  if (run.phase === DESCRIBE_RUN_PHASE.WARMING) {
    return (
      <div className="acx-media-selection__bulk-describe-progress" role="status" aria-live="polite">
        <span className="acx-media-selection__bulk-describe-status acx-media-selection__bulk-describe-status--running">
          <Loader2 className="acx-media-selection__bulk-describe-spin" aria-hidden="true" size={16} />
          {__('Warming GPU (about 2 min, first run only)…', 'alt-context')}
        </span>
        {cancelControl}
        {waitingNotice}
      </div>
    );
  }

  const processed = run.completed + run.failed + run.skipped;

  if (run.phase === DESCRIBE_RUN_PHASE.DESCRIBING) {
    const describingLabel = sprintf(__('Describing… %1$d/%2$d', 'alt-context'), processed, run.total);
    return (
      <div className="acx-media-selection__bulk-describe-progress" role="status" aria-live="polite">
        <span className="acx-media-selection__bulk-describe-status acx-media-selection__bulk-describe-status--running">
          <Loader2 className="acx-media-selection__bulk-describe-spin" aria-hidden="true" size={16} />
          {describingLabel}
        </span>
        <progress
          className="acx-media-selection__bulk-describe-bar"
          max={run.total > 0 ? run.total : 1}
          value={processed}
          aria-label={describingLabel}
        />
        {cancelControl}
        {waitingNotice}
        {stalledForSeconds !== null ? (
          <span className="acx-media-selection__bulk-describe-stall">
            <AlertTriangle aria-hidden="true" size={16} />
            {sprintf(__('No progress for %ds — the run may be stalled.', 'alt-context'), stalledForSeconds)}
          </span>
        ) : null}
      </div>
    );
  }

  if (run.phase === DESCRIBE_RUN_PHASE.COMPLETE) {
    const draftsReady = sprintf(
      _n(
        '✔ %1$d draft ready to review',
        '✔ %1$d drafts ready to review',
        run.completed,
        'alt-context',
      ),
      run.completed,
    );
    const failedSegment =
      run.failed > 0
        ? sprintf(_n(' · %1$d failed', ' · %1$d failed', run.failed, 'alt-context'), run.failed)
        : '';
    return (
      <div className="acx-media-selection__bulk-describe-progress" role="status" aria-live="polite">
        <span className="acx-media-selection__bulk-describe-status acx-media-selection__bulk-describe-status--success">
          <CheckCircle2 aria-hidden="true" size={16} />
          {`${draftsReady}${failedSegment}`}
        </span>
        <a className="button button-secondary" href={toDescriptionHistoryRun(run.run_id)}>
          {__('Review drafts', 'alt-context')}
        </a>
        {onDismiss ? (
          <button type="button" className="button button-link" onClick={onDismiss}>
            {__('Dismiss', 'alt-context')}
          </button>
        ) : null}
      </div>
    );
  }

  const meta = describeRunStatusMeta(status);
  const percent = progressFraction === null ? null : Math.round(progressFraction * 100);
  // Processed = every terminal item (completed + failed + skipped) so the bar
  // and count reflect true progress, not just successes.
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

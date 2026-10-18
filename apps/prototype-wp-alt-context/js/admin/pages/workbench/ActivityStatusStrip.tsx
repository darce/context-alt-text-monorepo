import { useEffect, useState, type JSX } from 'react';
import { AlertTriangle, CheckCircle2, Flame, Loader2, ScanSearch, XCircle } from 'lucide-react';
import { __, _n, sprintf } from '@wordpress/i18n';

import { GPU_STATE } from '../../api/describeApi';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { setDescribeProgressMounted } from '../../hooks/activeDescribeRun';
import {
  ACTIVITY_KIND,
  ACTIVITY_REASON,
  useActivityStatus,
  type ActivityKind,
  type ActivityStatus,
  type ScanActivitySource,
  type UseActivityStatusResult,
} from '../../hooks/useActivityStatus';
import { GPU_STATE_VOCABULARY } from './gpuStatePresentation';
import { SYNC_VOCABULARY } from './syncVocabulary';
import { useWorkbenchNav } from './WorkbenchNavContext';

export interface ActivityStatusStripProps {
  scan?: ScanActivitySource;
}

const KIND_ICON = {
  [ACTIVITY_KIND.IDLE]: ScanSearch,
  [ACTIVITY_KIND.SCANNING]: Loader2,
  [ACTIVITY_KIND.WARMING]: Flame,
  [ACTIVITY_KIND.DESCRIBING]: Loader2,
  [ACTIVITY_KIND.DONE]: CheckCircle2,
  [ACTIVITY_KIND.FAILED]: AlertTriangle,
} as const;

const spinningKind = (kind: ActivityKind): boolean =>
  kind === ACTIVITY_KIND.SCANNING || kind === ACTIVITY_KIND.WARMING || kind === ACTIVITY_KIND.DESCRIBING;

const formatEtaLabel = (etaSeconds: number | null): string | null => {
  if (etaSeconds === null) {
    return null;
  }
  const total = Math.max(0, Math.round(etaSeconds));
  if (total < 60) {
    return sprintf(__('~%ds remaining', 'alt-context'), total);
  }
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return sprintf(__('~%1$dm %2$ds remaining', 'alt-context'), minutes, seconds);
};

const headlineFor = (status: ActivityStatus): string => {
  switch (status.kind) {
    case ACTIVITY_KIND.SCANNING:
      return SYNC_VOCABULARY.scanningHeadline;
    case ACTIVITY_KIND.WARMING:
      return __('Warming GPU (first run only)…', 'alt-context');
    case ACTIVITY_KIND.DESCRIBING:
      return SYNC_VOCABULARY.describingHeadline;
    case ACTIVITY_KIND.DONE:
      return sprintf(
        _n('%d draft ready to review', '%d drafts ready to review', status.draftCount, 'alt-context'),
        status.draftCount,
      );
    case ACTIVITY_KIND.FAILED:
      return failedHeadline(status.reason);
    case ACTIVITY_KIND.IDLE:
      return idleHeadline(status);
    default: {
      const unreachable: never = status.kind;
      return unreachable;
    }
  }
};

const idleHeadline = (status: ActivityStatus): string => {
  if (status.gpuState === GPU_STATE.READY) {
    return GPU_STATE_VOCABULARY.readyNotice;
  }
  if (status.gpuState === GPU_STATE.DEGRADED) {
    return GPU_STATE_VOCABULARY.degradedNotice(status.draftCount);
  }
  if (status.gpuState === GPU_STATE.STOPPED) {
    return GPU_STATE_VOCABULARY.stoppedNotice;
  }
  return __('No activity', 'alt-context');
};

const failedHeadline = (reason: string | null): string => {
  switch (reason) {
    case ACTIVITY_REASON.GPU_WARMUP_TIMEOUT:
      return __('GPU warm-up timed out. Retry to continue.', 'alt-context');
    case ACTIVITY_REASON.DESCRIBE_POLL_ERROR:
      return SYNC_VOCABULARY.describeLost;
    case ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE:
      return __('Description Service status unavailable', 'alt-context');
    case ACTIVITY_REASON.CANCELLED:
      return __('Run cancelled', 'alt-context');
    case ACTIVITY_REASON.SCAN_FAILED:
      return __('People identification failed.', 'alt-context');
    case ACTIVITY_REASON.FAILED:
      return __('Describe run failed.', 'alt-context');
    default:
      return reason !== null && reason !== ''
        ? sprintf(__('Run failed (%s)', 'alt-context'), reason)
        : __('Run failed', 'alt-context');
  }
};

const reviewDraftsLabel = (draftCount: number): string =>
  sprintf(_n('Review %d draft', 'Review %d drafts', draftCount, 'alt-context'), draftCount);

export const ActivityStatusStrip = ({ scan }: ActivityStatusStripProps): JSX.Element => {
  const live: UseActivityStatusResult = useActivityStatus({ scan });
  const { status, actions, isCancelling } = live;
  const { setAdvancedOpen } = useWorkbenchNav();
  const [cancelOpen, setCancelOpen] = useState(false);

  useEffect(() => {
    setDescribeProgressMounted(true);
    return () => setDescribeProgressMounted(false);
  }, []);

  const Icon = status.kind === ACTIVITY_KIND.FAILED && status.reason === ACTIVITY_REASON.CANCELLED
    ? XCircle
    : KIND_ICON[status.kind];
  const etaLabel = formatEtaLabel(status.etaSeconds);
  const percent =
    status.progress === null ? null : Math.min(100, Math.max(0, Math.round(status.progress * 100)));
  const showWaitChrome =
    status.kind === ACTIVITY_KIND.SCANNING ||
    status.kind === ACTIVITY_KIND.WARMING ||
    status.kind === ACTIVITY_KIND.DESCRIBING;

  return (
    <div className="acx-activity-status-strip acx-sync-status" data-activity-kind={status.kind}>
      <div
        className="acx-activity-status-strip__status"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <span className="acx-activity-status-strip__headline acx-media-selection__detail-chip">
          <Icon
            className={spinningKind(status.kind) ? 'acx-media-selection__bulk-describe-spin' : undefined}
            aria-hidden="true"
            size={16}
          />
          {headlineFor(status)}
        </span>
        {percent !== null && showWaitChrome ? (
          <progress
            className="acx-activity-status-strip__progress acx-media-selection__bulk-describe-bar"
            max={100}
            value={percent}
            aria-label={headlineFor(status)}
          />
        ) : null}
        {showWaitChrome && etaLabel !== null ? (
          <span className="acx-activity-status-strip__eta">{etaLabel}</span>
        ) : null}
      </div>
      <div className="acx-activity-status-strip__run-actions">
        {actions.onCancel !== null ? (
          <button
            type="button"
            className="button button-link"
            disabled={isCancelling}
            onClick={() => setCancelOpen(true)}
          >
            {isCancelling ? __('Cancelling…', 'alt-context') : __('Cancel run', 'alt-context')}
          </button>
        ) : null}
        {actions.onRetry !== null ? (
          <button type="button" className="button" onClick={actions.onRetry}>
            {__('Retry', 'alt-context')}
          </button>
        ) : null}
        {actions.reviewDraftsHref !== null ? (
          <a className="button button-secondary" href={actions.reviewDraftsHref}>
            {reviewDraftsLabel(status.draftCount)}
          </a>
        ) : null}
        {actions.backToRunHref !== null ? (
          <a className="button button-link" href={actions.backToRunHref}>
            {GPU_STATE_VOCABULARY.backToRun}
          </a>
        ) : null}
      </div>
      <div className="acx-activity-status-strip__meta-actions">
        <button type="button" className="button" onClick={() => setAdvancedOpen(true)}>
          {__('Details', 'alt-context')}
        </button>
      </div>
      <ConfirmDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        onConfirm={() => {
          setCancelOpen(false);
          actions.onCancel?.();
        }}
        onCancel={() => setCancelOpen(false)}
        title={__('Cancel this run?', 'alt-context')}
        description={
          status.kind === ACTIVITY_KIND.SCANNING
            ? __('This stops people identification. Nothing already saved is removed.', 'alt-context')
            : __('This stops the describe run. Finished drafts stay available to review.', 'alt-context')
        }
        confirmLabel={__('Cancel run', 'alt-context')}
        isPending={isCancelling}
      />
    </div>
  );
};

/**
 * Live Workbench findings panel (E15-23).
 *
 * Non-accordion surface rendered between the job timeline and the media
 * queue. Summarizes what recognition found, shows representative previews,
 * and exposes one primary "Review next" action driven by the
 * useWorkbenchFindings view model.
 */

import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { AlertTriangle, Circle, ImageOff } from 'lucide-react';

import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { Avatar } from '../../../../components/ui/avatar';
import { isCroppableBbox } from '../../../../components/ui/faceGeometry';
import { isDedicatedFaceThumbUrl } from '../../../../components/ui/isDedicatedFaceThumbUrl';
import {
  CLUSTER_EVIDENCE,
  NEXT_ACTION_KIND,
  useWorkbenchFindings,
  type WorkbenchFindingPreview,
  type WorkbenchNextAction,
} from './useWorkbenchFindings';
import { gatedClusterCopy, REPRESENTATIVE_VOCABULARY } from './representativeVocabulary';
import { useSuggestionReviewQueries } from './useSuggestionReviewQueries';

/** Panel-level fallback chain (design B.2). First match wins. */
export const FINDINGS_PANEL_STATE = {
  LOADING: 'loading',
  ERROR: 'error',
  UNAVAILABLE: 'unavailable',
  DEGRADED: 'degraded',
  REPAIR: 'repair',
  EMPTY: 'empty',
  DATA: 'data',
} as const;

interface WorkbenchFindingsPanelProps {
  /** Scrolls/focuses the detailed findings queues below the panel. */
  onTargetFindings?: () => void;
}

/**
 * Findings-panel face preview box size in px.
 * WHY: 72px ≈ 17× the effective face pixels of the old 40px uncropped square —
 * sole owner of the preview box (Avatar / FaceThumbnail inline width/height).
 * TopClusterCard still uses its own 80px const + --acx-thumb-size-md (out of scope).
 */
export const FINDINGS_PREVIEW_SIZE_PX = 72;

/** Stable region label for ScanTabContent aria-labelledby (L3V-01 / A11Y-04). */
const FindingsRegionHeading = ({
  visuallyHidden = false,
}: {
  visuallyHidden?: boolean;
}): React.JSX.Element => (
  <h3
    id="acx-workbench-findings-heading"
    className={visuallyHidden ? 'screen-reader-text' : 'acx-findings-panel__title'}
  >
    {__('Recognition findings', 'alt-context')}
  </h3>
);

const nextActionHint = (action: WorkbenchNextAction): string | null => {
  switch (action.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return action.label
        ? sprintf(__('Confirm: %s', 'alt-context'), action.label)
        : __('Confirm the suggested match', 'alt-context');
    case NEXT_ACTION_KIND.MERGE:
      return __('Review the next merge candidate', 'alt-context');
    case NEXT_ACTION_KIND.NAME:
      return __('Review the next suggested name', 'alt-context');
    case NEXT_ACTION_KIND.CLUSTER:
      return __('Name the largest unlabeled group', 'alt-context');
    default:
      return null;
  }
};

/**
 * Alt for a preview chip. Confirmed labels may name a real crop; suggested /
 * machine labels are hedged (A11Y-02 / HAI-01). Uncropped fallbacks never claim
 * "Detected face".
 */
const previewAltText = (preview: WorkbenchFindingPreview, cropped: boolean): string => {
  if (preview.label) {
    if (preview.labelIsSuggested) {
      return cropped
        ? sprintf(__('Face image, possibly %s', 'alt-context'), preview.label)
        : sprintf(__('Reference image, possibly %s', 'alt-context'), preview.label);
    }
    return preview.label;
  }
  return cropped ? __('Detected face', 'alt-context') : __('Reference image', 'alt-context');
};

const usablePreviewUrl = (url: string | null | undefined): string | null => {
  if (typeof url !== 'string') {
    return null;
  }
  const trimmed = url.trim();
  return trimmed === '' ? null : trimmed;
};

const FindingsPreviewMissing = (): React.JSX.Element => (
  <div
    className="acx-findings-panel__preview acx-findings-panel__preview--missing"
    role="img"
    aria-label={REPRESENTATIVE_VOCABULARY.imageUnavailable}
    style={{ width: FINDINGS_PREVIEW_SIZE_PX, height: FINDINGS_PREVIEW_SIZE_PX }}
  >
    <ImageOff aria-hidden="true" size={20} />
    <span className="acx-findings-panel__preview-missing-label">{__('No image', 'alt-context')}</span>
  </div>
);

/**
 * Renderer order mirrors TopClusterCard (dedicated thumb → CSS face crop →
 * uncropped fallback). Previews are non-interactive evidence chips (A11Y-14:
 * target-size floor applies to interactive controls; these remain display-only).
 */
const FindingsPreview = ({ preview }: { preview: WorkbenchFindingPreview }): React.JSX.Element => {
  const useDedicatedThumb = isDedicatedFaceThumbUrl(preview.thumbUrl);
  const canCrop =
    typeof preview.mediaUrl === 'string' &&
    preview.mediaUrl.trim() !== '' &&
    isCroppableBbox(preview.bbox);

  if (useDedicatedThumb && preview.thumbUrl) {
    return (
      <Avatar
        src={preview.thumbUrl}
        sizePx={FINDINGS_PREVIEW_SIZE_PX}
        shape="square"
        alt={previewAltText(preview, true)}
        className="acx-findings-panel__preview"
      />
    );
  }

  if (canCrop && preview.mediaUrl && preview.bbox) {
    return (
      <FaceThumbnail
        mediaUrl={preview.mediaUrl}
        bbox={preview.bbox}
        sizePx={FINDINGS_PREVIEW_SIZE_PX}
        shape="square"
        alt={previewAltText(preview, true)}
        className="acx-findings-panel__preview"
      />
    );
  }

  const fallbackSrc = usablePreviewUrl(preview.thumbUrl) ?? usablePreviewUrl(preview.mediaUrl);
  if (!fallbackSrc) {
    return <FindingsPreviewMissing />;
  }

  return (
    <Avatar
      src={fallbackSrc}
      sizePx={FINDINGS_PREVIEW_SIZE_PX}
      shape="square"
      alt={previewAltText(preview, false)}
      className="acx-findings-panel__preview acx-findings-panel__preview--uncropped"
    />
  );
};

export const WorkbenchFindingsPanel = ({
  onTargetFindings,
}: WorkbenchFindingsPanelProps): React.JSX.Element => {
  const findings = useWorkbenchFindings();
  const { assignmentQuery, mergeQuery, nameQuery, topUnlabeledQuery } = useSuggestionReviewQueries();
  const {
    counts,
    previews,
    zeroEvidenceClusterCount,
    hasFindings,
    isLoading,
    isError,
    isTopUnlabeledError,
    isAssignmentError,
    isUnavailable,
    isReadOnly,
    nextAction,
  } = findings;

  // REV2-08: the control is labelled as reloading recognition findings, so it
  // must refetch every source that feeds them — name suggestions included.
  const handleRetryFindings = (): void => {
    void Promise.all([
      assignmentQuery.refetch(),
      mergeQuery.refetch(),
      nameQuery.refetch(),
      topUnlabeledQuery.refetch(),
    ]).catch(() => undefined);
  };

  const handleRetryTopUnlabeled = (): void => {
    void topUnlabeledQuery.refetch();
  };

  if (!hasFindings && isLoading) {
    return (
      <div
        className="acx-findings-panel acx-findings-panel--loading"
        data-findings-state={FINDINGS_PANEL_STATE.LOADING}
      >
        {/* L3V-01: keep aria-labelledby target mounted in non-success early returns. */}
        <FindingsRegionHeading visuallyHidden />
        <div role="status" aria-live="polite">
          <div className="acx-findings-panel__skeleton-row" aria-hidden="true" />
          <p className="acx-findings-panel__status">{__('Checking recognition findings…', 'alt-context')}</p>
        </div>
      </div>
    );
  }

  // UI-03 / UI-04: top-unlabeled (or primary) failure is not an empty backlog.
  // Gate the drained empty copy + its aria-live on a successful load only.
  // buildWorkbenchFindings already folds a zero-total top-unlabeled outage into
  // isError, so isError alone covers both failure modes here (UI-03 hook test).
  if (!hasFindings && isError) {
    return (
      <div
        className="acx-findings-panel acx-findings-panel--error"
        data-findings-state={FINDINGS_PANEL_STATE.ERROR}
      >
        <FindingsRegionHeading visuallyHidden />
        <div role="status" aria-live="polite">
          <p className="acx-findings-panel__status">
            <AlertTriangle aria-hidden="true" className="acx-findings-panel__status-icon" size={16} />
            {__('Could not load recognition findings.', 'alt-context')}
          </p>
          <button type="button" className="acx-button acx-button--secondary" onClick={handleRetryFindings}>
            {__('Retry', 'alt-context')}
          </button>
        </div>
      </div>
    );
  }

  if (!hasFindings && isUnavailable) {
    return (
      <div
        className="acx-findings-panel acx-findings-panel--unavailable"
        data-findings-state={FINDINGS_PANEL_STATE.UNAVAILABLE}
      >
        <FindingsRegionHeading visuallyHidden />
        <div role="status" aria-live="polite">
          <p className="acx-findings-panel__status">
            <Circle aria-hidden="true" className="acx-findings-panel__status-icon" size={16} />
            {__('Recognition findings are unavailable right now.', 'alt-context')}
          </p>
          <p className="acx-findings-panel__hint">
            {__('Check the Service API URL in Recognition API Settings.', 'alt-context')}
          </p>
        </div>
      </div>
    );
  }

  // BR-09: every actionable kind focuses the queue (cluster cards live there too).
  // Do not label-route CLUSTER — that unmounted the queue via the labeling panel.
  const handleReviewNext = (): void => {
    if (nextAction.kind === NEXT_ACTION_KIND.NONE) {
      return;
    }
    onTargetFindings?.();
  };

  const hint = nextActionHint(nextAction);
  // WHY: gate on nextAction (loaded queues), not counts.total (server totals) — a
  // positive total with an empty loaded page must not yield an enabled no-op button.
  const primaryDisabled = isReadOnly || nextAction.kind === NEXT_ACTION_KIND.NONE;

  const panelState = isTopUnlabeledError ? FINDINGS_PANEL_STATE.DEGRADED : FINDINGS_PANEL_STATE.DATA;
  // REV1-02: a mounted repair row is not an empty backlog (B.3).
  const findingsState = !hasFindings
    ? zeroEvidenceClusterCount > 0
      ? FINDINGS_PANEL_STATE.REPAIR
      : FINDINGS_PANEL_STATE.EMPTY
    : panelState;

  return (
    <div className="acx-findings-panel" data-findings-state={findingsState}>
      <FindingsRegionHeading />

      {isReadOnly && (
        <p className="acx-findings-panel__notice">
          {__(
            'Findings are visible while local sync catches up. Curation stays disabled until projected results are available locally.',
            'alt-context',
          )}
        </p>
      )}

      {/* One live region for counts + repair copy. Hidden on true empty so only
          the empty-state region announces the zero state. Resync stays outside. */}
      {(hasFindings || zeroEvidenceClusterCount > 0) && (
        <div role="status" aria-live="polite">
          {hasFindings && (
            <ul className="acx-findings-panel__counts">
              <li className="acx-findings-panel__count">
                {sprintf(_n('%d to review', '%d to review', counts.assignments, 'alt-context'), counts.assignments)}
              </li>
              <li className="acx-findings-panel__count">
                {sprintf(_n('%d merge candidate', '%d merge candidates', counts.merges, 'alt-context'), counts.merges)}
              </li>
              <li className="acx-findings-panel__count">
                {sprintf(_n('%d suggested name', '%d suggested names', counts.names, 'alt-context'), counts.names)}
              </li>
              <li className="acx-findings-panel__count">
                {isTopUnlabeledError ? (
                  <span className="acx-findings-panel__degraded-chip">
                    <AlertTriangle aria-hidden="true" className="acx-findings-panel__status-icon" size={14} />
                    {__('Unlabeled groups unavailable', 'alt-context')}
                    <button
                      type="button"
                      className="acx-button acx-button--secondary acx-button--small"
                      onClick={handleRetryFindings}
                    >
                      {__('Retry', 'alt-context')}
                    </button>
                  </span>
                ) : (
                  sprintf(
                    _n('%d unlabeled group', '%d unlabeled groups', counts.unlabeledClusters, 'alt-context'),
                    counts.unlabeledClusters,
                  )
                )}
              </li>
            </ul>
          )}
          {zeroEvidenceClusterCount > 0 && (
            <>
              <p id="acx-findings-panel-repair-copy" className="acx-findings-panel__status">
                <AlertTriangle aria-hidden="true" className="acx-findings-panel__status-icon" size={16} />
                {gatedClusterCopy(zeroEvidenceClusterCount)}
              </p>
              <p className="acx-findings-panel__hint">
                {__('They are hidden from review until their faces sync.', 'alt-context')}
              </p>
            </>
          )}
        </div>
      )}

      {previews.length > 0 && (
        <div className="acx-findings-panel__previews">
          {previews.map((preview) => (
            <FindingsPreview key={preview.key} preview={preview} />
          ))}
        </div>
      )}

      {zeroEvidenceClusterCount > 0 && (
        <div className="acx-findings-panel__repair" data-cluster-evidence={CLUSTER_EVIDENCE.ZERO}>
          <button
            type="button"
            className="acx-button acx-button--secondary acx-button--small"
            onClick={handleRetryTopUnlabeled}
            aria-describedby="acx-findings-panel-repair-copy"
          >
            {__('Resync', 'alt-context')}
          </button>
        </div>
      )}

      {/* UI-04: empty drain copy is only for a successful zero — every failure
          mode (including a zero-total top-unlabeled outage) returns above.
          A zero-evidence-only backlog is a repair state, not "all caught up". */}
      {/* REV2-01: an assignment-only outage leaves the other queues returning
          successful empties, so hasFindings is false without isError ever being
          set. Announcing "No findings yet" there tells the operator the backlog
          is clear while the primary review queue is down. Same treatment as the
          top-unlabeled degraded chip: name the outage, offer the retry. */}
      {!hasFindings && zeroEvidenceClusterCount === 0 && isAssignmentError && (
        <>
          <p
            id="acx-findings-panel-assignment-outage"
            className="acx-findings-panel__status"
            role="status"
            aria-live="polite"
          >
            <AlertTriangle aria-hidden="true" className="acx-findings-panel__status-icon" size={16} />
            {__('Face assignments unavailable — this is not an empty backlog.', 'alt-context')}
          </p>
          <div className="acx-findings-panel__repair">
            <button
              type="button"
              className="acx-button acx-button--secondary acx-button--small"
              onClick={handleRetryFindings}
              aria-describedby="acx-findings-panel-assignment-outage"
            >
              {__('Retry', 'alt-context')}
            </button>
          </div>
        </>
      )}

      {!hasFindings && zeroEvidenceClusterCount === 0 && !isAssignmentError && (
        <p className="acx-findings-panel__empty" role="status" aria-live="polite">
          {__('No findings yet. Run a scan and new findings will appear here automatically.', 'alt-context')}
        </p>
      )}

      <div className="acx-findings-panel__actions">
        <button
          type="button"
          className="acx-button acx-button--primary"
          onClick={handleReviewNext}
          disabled={primaryDisabled}
        >
          {__('Review next', 'alt-context')}
          {hint && <span className="acx-findings-panel__next-hint"> {hint}</span>}
        </button>
        {hasFindings && (
          <button
            type="button"
            className="acx-button acx-button--secondary acx-button--small"
            onClick={() => onTargetFindings?.()}
          >
            {__('View all findings', 'alt-context')}
          </button>
        )}
      </div>
    </div>
  );
};

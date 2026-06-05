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

import { Avatar } from '../../../../components/ui/avatar';
import { NEXT_ACTION_KIND, useWorkbenchFindings, type WorkbenchNextAction } from './useWorkbenchFindings';

interface WorkbenchFindingsPanelProps {
  /** Opens the existing cluster labeling drawer. */
  onLabel: (clusterId: string) => void;
  /** Scrolls/focuses the detailed findings queues below the panel. */
  onTargetFindings?: () => void;
}

const PREVIEW_SIZE_PX = 40;

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

export const WorkbenchFindingsPanel = ({
  onLabel,
  onTargetFindings,
}: WorkbenchFindingsPanelProps): React.JSX.Element => {
  const findings = useWorkbenchFindings();
  const { counts, previews, hasFindings, isLoading, isError, isUnavailable, isReadOnly, nextAction } = findings;

  if (!hasFindings && isLoading) {
    return (
      <div className="acx-findings-panel acx-findings-panel--loading" role="status" aria-live="polite">
        <p className="acx-findings-panel__status">{__('Checking recognition findings…', 'alt-context')}</p>
      </div>
    );
  }

  if (!hasFindings && isError) {
    return (
      <div className="acx-findings-panel acx-findings-panel--error" role="status" aria-live="polite">
        <p className="acx-findings-panel__status">{__('Could not load recognition findings.', 'alt-context')}</p>
      </div>
    );
  }

  if (!hasFindings && isUnavailable) {
    return (
      <div className="acx-findings-panel acx-findings-panel--unavailable" role="status" aria-live="polite">
        <p className="acx-findings-panel__status">
          {__('Recognition findings are unavailable right now.', 'alt-context')}
        </p>
      </div>
    );
  }

  const handleReviewNext = (): void => {
    if (nextAction.kind === NEXT_ACTION_KIND.CLUSTER) {
      onLabel(nextAction.clusterId);
      return;
    }
    if (
      nextAction.kind === NEXT_ACTION_KIND.ASSIGNMENT ||
      nextAction.kind === NEXT_ACTION_KIND.MERGE ||
      nextAction.kind === NEXT_ACTION_KIND.NAME
    ) {
      onTargetFindings?.();
    }
  };

  const hint = nextActionHint(nextAction);
  // WHY: gate on nextAction (loaded queues), not counts.total (server totals) — a
  // positive total with an empty loaded page must not yield an enabled no-op button.
  const primaryDisabled = isReadOnly || nextAction.kind === NEXT_ACTION_KIND.NONE;

  return (
    <div className="acx-findings-panel">
      <h3 className="acx-findings-panel__title">{__('Recognition findings', 'alt-context')}</h3>

      {isReadOnly && (
        <p className="acx-findings-panel__notice">
          {__(
            'Findings are visible while local sync catches up. Curation stays disabled until projected results are available locally.',
            'alt-context',
          )}
        </p>
      )}

      {/* Live region: announces findings appearing/updating after a scan without a reload.
          Hidden when empty so only the empty-state region announces the zero state. */}
      {hasFindings && (
        <div role="status" aria-live="polite">
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
              {sprintf(
                _n('%d unlabeled group', '%d unlabeled groups', counts.unlabeledClusters, 'alt-context'),
                counts.unlabeledClusters,
              )}
            </li>
          </ul>
        </div>
      )}

      {previews.length > 0 && (
        <div className="acx-findings-panel__previews">
          {previews.map((preview) => (
            <Avatar
              key={preview.key}
              src={preview.thumbUrl ?? preview.mediaUrl ?? ''}
              sizePx={PREVIEW_SIZE_PX}
              shape="square"
              alt={preview.label ?? __('Detected face', 'alt-context')}
              className="acx-findings-panel__preview"
            />
          ))}
        </div>
      )}

      {!hasFindings && (
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

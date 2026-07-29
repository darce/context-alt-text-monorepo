import React, { useId, useRef, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { useDescribeRunApply } from '../hooks/useDescribeRunApply';
import type { ApplyDescribeRunResponse, DescribeRunItem } from '../api/describeApi';
import { toDescriptionHistory } from '../navigation/appLinks';

interface DescribeRunApplyViewProps {
  runId: string;
}

const PARTIAL_LABEL_CAP = 5;

const itemHeading = (item: DescribeRunItem): string =>
  item.caption && item.caption.trim() !== ''
    ? item.caption
    : sprintf(__('Media %d', 'alt-context'), item.media_id);

/** Label a partial media id via the run item when present; fall back to Media N. */
const partialItemLabel = (mediaId: number, itemsById: Map<number, DescribeRunItem>): string => {
  const item = itemsById.get(mediaId);
  return item ? itemHeading(item) : sprintf(__('Media %d', 'alt-context'), mediaId);
};

/**
 * Cap an unbounded media-id clause (first 5 + "and N more") and prefer item
 * headings over bare integers so the summary stays scannable. [RLSE-04]
 */
const formatPartialLabels = (partialIds: number[], itemsById: Map<number, DescribeRunItem>): string => {
  const labels = partialIds.map((id) => partialItemLabel(id, itemsById));
  if (labels.length <= PARTIAL_LABEL_CAP) {
    return labels.join(', ');
  }
  const head = labels.slice(0, PARTIAL_LABEL_CAP).join(', ');
  return sprintf(
    __('%1$s, and %2$d more', 'alt-context'),
    head,
    labels.length - PARTIAL_LABEL_CAP,
  );
};

/**
 * Build the apply-result live-region text from the last successful payload.
 * Omits the applied sentence at zero, caps partial labels, and appends an
 * explicit history-completion line after a successful recovery. [RLSE-05]
 */
const buildApplyResultText = (
  data: ApplyDescribeRunResponse,
  itemsById: Map<number, DescribeRunItem>,
  historyRecovered: boolean,
): string => {
  const parts: string[] = [];

  if (data.applied.length > 0) {
    parts.push(sprintf(__('Applied %d descriptions.', 'alt-context'), data.applied.length));
  }

  if (data.partial.length > 0) {
    parts.push(
      sprintf(
        // Surface named rows so a multi-item run identifies the outstanding
        // provenance completions; "apply again" is honest: server completes
        // provenance when alt already matches the draft (non-clobber). [RLSE-05]
        __('%1$d had alt text saved (%2$s); apply again so they appear in history.', 'alt-context'),
        data.partial.length,
        formatPartialLabels(data.partial, itemsById),
      ),
    );
  } else if (historyRecovered) {
    parts.push(
      __('History is now complete for items that needed a second apply.', 'alt-context'),
    );
  }

  if (data.skipped_existing.length > 0) {
    parts.push(
      sprintf(__('Skipped %d with existing alt text.', 'alt-context'), data.skipped_existing.length),
    );
  }
  if (data.skipped_no_draft.length > 0) {
    parts.push(sprintf(__('%d had no draft.', 'alt-context'), data.skipped_no_draft.length));
  }
  if (data.failed.length > 0) {
    parts.push(sprintf(__('%d failed to write.', 'alt-context'), data.failed.length));
  }
  if (data.skipped_invalid.length > 0) {
    parts.push(
      sprintf(__('%d were not valid attachments.', 'alt-context'), data.skipped_invalid.length),
    );
  }

  return parts.join(' ').trim();
};

/**
 * INT-01d: the operator's read/apply surface for one completed describe run.
 * Drafts with no existing alt apply behind a single primary bulk action (low
 * friction); drafts that would clobber existing operator alt are bucketed behind
 * an explicit per-item overwrite opt-in and never applied by default. Items with
 * no usable draft (failed/skipped) are listed as informational only.
 *
 * Write policy vs single-image path: this bulk view is intentionally more
 * permissive than the guarded single-image write policy
 * (`apply_alt_text_write_policy`). The single-image path has no prior-attempt
 * concept — existing alt without `force` is always `skipped_existing_alt`. The
 * bulk path can complete a provenance write that an earlier apply in the same
 * run left half-done (alt landed, history/provenance did not): the server
 * treats matching alt + missing provenance as a non-clobber recovery, not as a
 * destructive overwrite. That recovery fall-through has no single-image
 * equivalent; do not treat the two paths as policy-equivalent.
 */
export const DescribeRunApplyView = ({ runId }: DescribeRunApplyViewProps): React.JSX.Element => {
  const { itemsQuery, buckets, apply } = useDescribeRunApply(runId);
  const [overwriteIds, setOverwriteIds] = useState<Set<number>>(new Set());
  // Outstanding partial media ids survive the next mutation (including failure).
  // Cleared only when a success reports the id is no longer partial. [INT-11]
  const [outstandingPartialIds, setOutstandingPartialIds] = useState<number[]>([]);
  const outstandingPartialIdsRef = useRef<number[]>([]);
  // Last successful payload kept for the live region so a failed retry does not
  // unmount the partial summary. [RLSE-05][INT-11]
  const [lastResult, setLastResult] = useState<ApplyDescribeRunResponse | null>(null);
  // True when the previous success had partials and the latest does not —
  // confirms the promised history completion closed. [RLSE-05]
  const [historyRecovered, setHistoryRecovered] = useState(false);
  const disabledReasonId = useId();

  /**
   * Reconcile local recovery state from a landed write. Called from the per-
   * mutate onSuccess so a failed retry never clears outstanding partials —
   * only a later success that omits an id from `partial` does. [INT-11]
   */
  const onApplySuccess = (data: ApplyDescribeRunResponse): void => {
    setOverwriteIds(new Set());
    const prev = outstandingPartialIdsRef.current;
    const next = data.partial;
    // Clear an id only when this success reports it is no longer partial.
    outstandingPartialIdsRef.current = next;
    setOutstandingPartialIds(next);
    setLastResult(data);
    setHistoryRecovered(prev.length > 0 && next.length === 0);
  };

  const toggleOverwrite = (mediaId: number): void => {
    setOverwriteIds((current) => {
      const next = new Set(current);
      if (next.has(mediaId)) {
        next.delete(mediaId);
      } else {
        next.add(mediaId);
      }
      return next;
    });
  };

  const header = (
    <header className="acx-history__hero">
      <p className="acx-dashboard__eyebrow">{__('Bulk describe', 'alt-context')}</p>
      <h1 className="acx-dashboard__title">{__('Apply generated descriptions', 'alt-context')}</h1>
      <a className="acx-run-apply__back" href={toDescriptionHistory()}>
        {__('Back to full history', 'alt-context')}
      </a>
    </header>
  );

  if (itemsQuery.isLoading) {
    return (
      <section className="acx-history acx-run-apply" aria-label={__('Apply run drafts', 'alt-context')}>
        {header}
        <p>{__('Loading run drafts…', 'alt-context')}</p>
      </section>
    );
  }

  if (itemsQuery.isError) {
    return (
      <section className="acx-history acx-run-apply" aria-label={__('Apply run drafts', 'alt-context')}>
        {header}
        <section className="acx-dashboard__panel acx-history__panel">
          <h2>{__('Could not load this run’s drafts.', 'alt-context')}</h2>
          <button type="button" className="acx-button acx-button--secondary" onClick={() => void itemsQuery.refetch()}>
            {__('Retry', 'alt-context')}
          </button>
        </section>
      </section>
    );
  }

  const { withoutAlt, withExistingAlt, noDraft } = buckets;
  const allItems = itemsQuery.data?.items ?? [];
  const itemsById = new Map(allItems.map((item) => [item.media_id, item]));
  const outstandingPartialSet = new Set(outstandingPartialIds);

  // Partials after a write sit in withExistingAlt (existing_alt flipped true).
  // Present them as history-completion, not as overwrite candidates. [RLSE-04]
  const historyCompletionItems = outstandingPartialIds
    .map((id) => itemsById.get(id))
    .filter((item): item is DescribeRunItem => item !== undefined);
  const overwriteCandidates = withExistingAlt.filter(
    (item) => !outstandingPartialSet.has(item.media_id),
  );

  const hasApplicable =
    withoutAlt.length > 0 || overwriteCandidates.length > 0 || outstandingPartialIds.length > 0;
  const selectedOverwrites = overwriteCandidates.filter((item) => overwriteIds.has(item.media_id));
  // Explicit selections (safe + overwrite). Outstanding partials are completed
  // implicitly by the server on the same request — count them in the label. [BR-91]
  const applyCount = withoutAlt.length + selectedOverwrites.length;
  const partialCompletionCount = outstandingPartialIds.length;
  const totalWriteCount = applyCount + partialCompletionCount;
  const canApply = totalWriteCount > 0;
  const partialRetryOnly = partialCompletionCount > 0 && applyCount === 0;
  const primaryLabel = partialRetryOnly
    ? sprintf(__('Apply again to complete history for %d', 'alt-context'), partialCompletionCount)
    : withoutAlt.length > 0 && selectedOverwrites.length === 0 && partialCompletionCount === 0
      ? sprintf(__('Apply all %d without alt text', 'alt-context'), withoutAlt.length)
      : sprintf(__('Apply %d descriptions', 'alt-context'), totalWriteCount);

  const applyDisabled = !canApply || apply.isPending;
  const showDisabledReason = !canApply && !apply.isPending;

  const onApply = (): void => {
    apply.mutate(selectedOverwrites.map((item) => item.media_id), {
      onSuccess: onApplySuccess,
    });
  };

  // Mount-then-mutate: always render the live region so ATs track it before the
  // first result text arrives. Empty while quiet. [A11Y-21]
  const resultText = lastResult
    ? buildApplyResultText(lastResult, itemsById, historyRecovered)
    : '';

  const safePanelHeading =
    withoutAlt.length > 0
      ? sprintf(__('%d descriptions ready to apply', 'alt-context'), withoutAlt.length)
      : historyCompletionItems.length > 0
        ? sprintf(
            __('%d need history completion', 'alt-context'),
            historyCompletionItems.length,
          )
        : __('No new descriptions without existing alt text', 'alt-context');

  const safePanelBody =
    withoutAlt.length > 0
      ? __('These images have no alt text yet, so their drafts apply safely.', 'alt-context')
      : historyCompletionItems.length > 0
        ? __(
            'Alt text was already saved for these images. Apply again so they appear in history — this does not overwrite alt text.',
            'alt-context',
          )
        : __(
            'All drafts for this run already have alt text. Check images below to overwrite.',
            'alt-context',
          );

  return (
    <section className="acx-history acx-run-apply" aria-label={__('Apply run drafts', 'alt-context')}>
      {header}

      <div
        className={resultText ? 'acx-dashboard__panel acx-run-apply__result' : undefined}
        role="status"
        aria-live="polite"
        data-testid="acx-run-apply-status"
      >
        {resultText}
      </div>

      {apply.isError ? (
        <div className="acx-error-state" role="alert">
          <span aria-hidden="true">⚠</span>{' '}
          {__('Could not apply the run drafts. Try again.', 'alt-context')}
          {outstandingPartialIds.length > 0
            ? ` ${sprintf(
                __('History is still incomplete for %s.', 'alt-context'),
                formatPartialLabels(outstandingPartialIds, itemsById),
              )}`
            : null}
        </div>
      ) : null}

      {!hasApplicable ? (
        <section className="acx-dashboard__panel acx-history__panel">
          <h2>{__('No drafts from this run can be applied.', 'alt-context')}</h2>
          <p>{__('Every described item either failed or produced no draft text.', 'alt-context')}</p>
        </section>
      ) : (
        <>
          <section className="acx-dashboard__panel acx-run-apply__safe" aria-label={__('Ready to apply', 'alt-context')}>
            <h2>{safePanelHeading}</h2>
            <p>{safePanelBody}</p>
            <ul className="acx-run-apply__list">
              {withoutAlt.map((item) => (
                <li key={item.media_id} className="acx-run-apply__item">
                  <span className="acx-run-apply__item-heading">{itemHeading(item)}</span>
                  <span className="acx-run-apply__draft">{item.alt_text_draft}</span>
                  <span className="acx-run-apply__media-id">{sprintf(__('Media %d', 'alt-context'), item.media_id)}</span>
                </li>
              ))}
              {/* When safe drafts coexist with outstanding partials, list the
                  history-completion rows under the same primary so the operator
                  sees the full write set the button will perform. */}
              {historyCompletionItems.map((item) => (
                <li key={`partial-${item.media_id}`} className="acx-run-apply__item">
                  <span className="acx-run-apply__item-heading">{itemHeading(item)}</span>
                  <span className="acx-run-apply__draft">{item.alt_text_draft}</span>
                  <span className="acx-run-apply__media-id">
                    {__('needs history completion (no overwrite)', 'alt-context')}
                  </span>
                </li>
              ))}
            </ul>
            {showDisabledReason ? (
              <span id={disabledReasonId} className="screen-reader-text">
                {__(
                  'Nothing selected to apply. Check an image below to overwrite its alt text.',
                  'alt-context',
                )}
              </span>
            ) : null}
            <button
              type="button"
              className="acx-button acx-button--primary"
              disabled={applyDisabled}
              aria-disabled={applyDisabled ? true : undefined}
              aria-describedby={showDisabledReason ? disabledReasonId : undefined}
              onClick={onApply}
            >
              {apply.isPending ? __('Applying…', 'alt-context') : primaryLabel}
            </button>
          </section>

          {overwriteCandidates.length > 0 ? (
            <section
              className="acx-dashboard__panel acx-run-apply__existing"
              aria-label={__('Existing alt text', 'alt-context')}
            >
              <h2>
                {sprintf(__('%d images already have alt text', 'alt-context'), overwriteCandidates.length)}
              </h2>
              <p>{__('Check an image to overwrite its alt text with the new draft when you apply.', 'alt-context')}</p>
              <ul className="acx-run-apply__list">
                {overwriteCandidates.map((item) => (
                  <li key={item.media_id} className="acx-run-apply__item acx-run-apply__item--existing">
                    <label className="acx-run-apply__overwrite">
                      <input
                        type="checkbox"
                        checked={overwriteIds.has(item.media_id)}
                        onChange={() => toggleOverwrite(item.media_id)}
                        aria-label={sprintf(
                          __('Overwrite existing alt text for media %d', 'alt-context'),
                          item.media_id,
                        )}
                      />
                      <span className="acx-run-apply__item-heading">{itemHeading(item)}</span>
                    </label>
                    <span className="acx-run-apply__draft">{item.alt_text_draft}</span>
                    <span className="acx-run-apply__media-id">{sprintf(__('Media %d', 'alt-context'), item.media_id)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}

      {noDraft.length > 0 ? (
        <section
          className="acx-dashboard__panel acx-run-apply__no-draft"
          data-testid="acx-run-apply-no-draft"
          aria-label={__('Skipped items', 'alt-context')}
        >
          <h2>{sprintf(__('%d items produced no draft', 'alt-context'), noDraft.length)}</h2>
          <ul className="acx-run-apply__list">
            {noDraft.map((item) => (
              <li key={item.media_id} className="acx-run-apply__item">
                {sprintf(__('Media %1$d — %2$s', 'alt-context'), item.media_id, item.status)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
};

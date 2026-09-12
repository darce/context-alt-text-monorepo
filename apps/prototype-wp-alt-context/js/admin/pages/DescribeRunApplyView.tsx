import React, { useId, useRef, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { useDescribeRunApply } from '../hooks/useDescribeRunApply';
import {
  DESCRIBE_RESULT_TIER,
  NAMING_PROVENANCE_STATUS,
  NAMING_REALIZER,
  parseNamingProvenance,
  type ApplyDescribeRunResponse,
  type DescribeRunItem,
  type NamingProvenance,
  type NamingRealizer,
} from '../api/describeApi';
import { toDescriptionHistory } from '../navigation/appLinks';
import { EmptyState, EmptyStateVariant } from '../components/ui/EmptyState';

interface DescribeRunApplyViewProps {
  runId: string;
}

const PARTIAL_LABEL_CAP = 5;

const tierBadgeFor = (item: DescribeRunItem): React.JSX.Element => {
  const label =
    item.tier === DESCRIBE_RESULT_TIER.FINAL_GPU
      ? __('Compute tier: Final (GPU)', 'alt-context')
      : item.tier === DESCRIBE_RESULT_TIER.PROVISIONAL_CPU
        ? __('Compute tier: Provisional (CPU)', 'alt-context')
        : __('Compute tier: Unknown', 'alt-context');

  return (
    <span className="acx-history__badge" data-testid={`acx-run-apply-tier-${item.media_id}`}>
      {label}
    </span>
  );
};

const itemHeading = (item: DescribeRunItem): string =>
  item.caption && item.caption.trim() !== '' ? item.caption : sprintf(__('Media %d', 'alt-context'), item.media_id);

interface NamingBadgeCopy {
  label: string;
  description: string;
  icon: string;
}

const appliedRealizerLabel = (realizer: NamingRealizer | null): string | null => {
  if (realizer === NAMING_REALIZER.GROUNDED) {
    return __('grounded', 'alt-context');
  }
  if (realizer === NAMING_REALIZER.POSITIONAL_FALLBACK) {
    return __('positional', 'alt-context');
  }
  return null;
};

const namingBadgeCopy = (naming: NamingProvenance): NamingBadgeCopy | null => {
  switch (naming.status) {
    case NAMING_PROVENANCE_STATUS.APPLIED: {
      const names = naming.names_applied.join(', ');
      const realizer = appliedRealizerLabel(naming.realizer);
      const label = realizer
        ? sprintf(__('Names: %1$s · %2$s', 'alt-context'), names, realizer)
        : sprintf(__('Names: %s', 'alt-context'), names);
      const description =
        naming.realizer === NAMING_REALIZER.POSITIONAL_FALLBACK
          ? __('Names were applied using positional fallback.', 'alt-context')
          : naming.realizer === NAMING_REALIZER.GROUNDED
            ? __('Names were applied using grounded phrase alignment.', 'alt-context')
            : __('Names were applied, but the naming method was not reported.', 'alt-context');
      return { label, description, icon: '✓' };
    }
    case NAMING_PROVENANCE_STATUS.DISABLED:
      return {
        label: __('No names (disabled)', 'alt-context'),
        description: __('Names were not applied because naming is disabled.', 'alt-context'),
        icon: '⊘',
      };
    case NAMING_PROVENANCE_STATUS.SKIPPED_BUDGET:
      return {
        label: __('Names skipped (time budget)', 'alt-context'),
        description: __('Names were not applied because the time budget was reached.', 'alt-context'),
        icon: '◷',
      };
    case NAMING_PROVENANCE_STATUS.NO_FACES:
      return {
        label: __('No faces', 'alt-context'),
        description: __('Names were not applied because no faces were detected.', 'alt-context'),
        icon: '○',
      };
    default:
      return null;
  }
};

const namingBadgeFor = (item: DescribeRunItem): React.JSX.Element | null => {
  const provenance = item.provenance;
  if (!provenance || typeof provenance !== 'object' || !('naming' in provenance)) {
    return null;
  }

  const naming = parseNamingProvenance(provenance.naming);
  if (!naming) {
    return null;
  }
  const copy = namingBadgeCopy(naming);
  if (!copy) {
    return null;
  }

  return (
    <span
      className="acx-history__badge acx-history__recovery"
      data-testid={`acx-run-apply-naming-${item.media_id}`}
      title={copy.description}
      aria-label={copy.description}
    >
      <span className="acx-history__recovery-icon" aria-hidden="true">
        {copy.icon}
      </span>
      <span>{copy.label}</span>
    </span>
  );
};

/**
 * Label a partial media id. Always surface the media id when a non-empty caption
 * is used as the heading so colliding captions remain distinguishable. [BR-111]
 */
const partialItemLabel = (mediaId: number, itemsById: Map<number, DescribeRunItem>): string => {
  const item = itemsById.get(mediaId);
  if (!item) {
    return sprintf(__('Media %d', 'alt-context'), mediaId);
  }
  if (item.caption && item.caption.trim() !== '') {
    return sprintf(__('%1$s (Media %2$d)', 'alt-context'), item.caption, mediaId);
  }
  return sprintf(__('Media %d', 'alt-context'), mediaId);
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
  return sprintf(__('%1$s, and %2$d more', 'alt-context'), head, labels.length - PARTIAL_LABEL_CAP);
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
  historyIncompleteIds: number[],
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
    parts.push(__('History is now complete for items that needed a second apply.', 'alt-context'));
  } else if (historyIncompleteIds.length > 0) {
    // Prior partials left the outstanding set without landing in applied
    // (failed / skipped_*) — never claim recovery. [BR-103][RLSE-05]
    parts.push(
      sprintf(
        __('History is still incomplete for %s.', 'alt-context'),
        formatPartialLabels(historyIncompleteIds, itemsById),
      ),
    );
  }

  if (data.skipped_existing.length > 0) {
    parts.push(sprintf(__('Skipped %d with existing alt text.', 'alt-context'), data.skipped_existing.length));
  }
  if (data.skipped_no_draft.length > 0) {
    parts.push(sprintf(__('%d had no draft.', 'alt-context'), data.skipped_no_draft.length));
  }
  if (data.failed.length > 0) {
    // R21-BR-09: bulk `failed` after an alt-landed provenance/marker miss is
    // not "nothing written" — alt may already be stored. Keep copy honest.
    parts.push(
      sprintf(
        __('%d could not finish (alt may already be saved; provenance incomplete).', 'alt-context'),
        data.failed.length,
      ),
    );
  }
  if (data.skipped_invalid.length > 0) {
    parts.push(sprintf(__('%d were not valid attachments.', 'alt-context'), data.skipped_invalid.length));
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
 * Write policy vs single-image path: both bulk apply and single-image describe
 * (`apply_alt_text_write_policy`) treat matching alt + missing/incomplete
 * provenance as a non-clobber recovery. Single-image without `force`: a
 * genuinely different existing alt is still `skipped_existing_alt`; when the
 * stored alt already equals the draft and only provenance needs repair, the
 * write path restamps provenance and reports `provenance_healed` (success, not
 * an overwrite). With identity-complete provenance, only the draft key is
 * healed and the status remains `skipped_existing_alt`. `forced_overwrite` is
 * reserved for `force=true` success. Bulk apply uses the same recovery idea for
 * half-done prior attempts in a run (alt landed, history did not).
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
  // True when every previously outstanding id landed in applied. [BR-103][RLSE-05]
  const [historyRecovered, setHistoryRecovered] = useState(false);
  // Prior outstanding ids that left partial without landing in applied. [BR-103]
  const [historyIncompleteIds, setHistoryIncompleteIds] = useState<number[]>([]);
  const disabledReasonId = useId();

  /**
   * Reconcile local recovery state from a landed write. Called from the per-
   * mutate onSuccess so a failed retry never clears outstanding partials —
   * only a later success that omits an id from `partial` does. [INT-11]
   *
   * Replace (do not union) with data.partial: a recovered id must leave the
   * outstanding set on success. [BR-120]
   */
  const onApplySuccess = (data: ApplyDescribeRunResponse): void => {
    setOverwriteIds(new Set());
    const prev = outstandingPartialIdsRef.current;
    const next = data.partial;
    const appliedSet = new Set(data.applied);
    // Clear an id only when this success reports it is no longer partial.
    outstandingPartialIdsRef.current = next;
    setOutstandingPartialIds(next);
    setLastResult(data);
    // History is complete only when every previously outstanding id is present
    // in applied — not merely when the partial bucket emptied into skipped/failed.
    // [BR-103][RLSE-05]
    const recovered = prev.length > 0 && prev.every((id) => appliedSet.has(id));
    setHistoryRecovered(recovered);
    const incomplete = prev.filter((id) => !appliedSet.has(id) && !next.includes(id));
    setHistoryIncompleteIds(incomplete);
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
      <p className="acx-dashboard__title">{__('Apply generated descriptions', 'alt-context')}</p>
      <a className="acx-run-apply__back" href={toDescriptionHistory()}>
        {__('Back to full history', 'alt-context')}
      </a>
    </header>
  );

  // Mount-then-mutate: the live region is a stable sibling of every branch so
  // it never unmounts across loading / items-error / main. [BR-117][A11Y-21]
  // Prefer retained items (RQ keeps prior data on error; also any in-flight
  // placeholder) when recovery state is live so a post-apply items refetch
  // failure cannot strip the retry affordance. [BR-127][INT-11]
  const hasRecoveryContext = lastResult !== null || outstandingPartialIds.length > 0;
  const retainedData = itemsQuery.data;
  const preferRetainedOnError = itemsQuery.isError && hasRecoveryContext && retainedData !== undefined;
  const showLoading = itemsQuery.isLoading && retainedData === undefined;
  const showItemsError = itemsQuery.isError && !preferRetainedOnError;
  const showMain = retainedData !== undefined && !showItemsError;

  const { withoutAlt: withoutAltRaw, withExistingAlt, noDraft } = buckets;
  const allItems = retainedData?.items ?? [];
  const itemsById = new Map(allItems.map((item) => [item.media_id, item]));
  const outstandingPartialSet = new Set(outstandingPartialIds);

  // Exclude outstanding partials from the safe bucket the same way overwrite
  // candidates exclude them. While the items refetch is still in flight,
  // existing_alt is still false so the same id would otherwise sit in both
  // withoutAlt and historyCompletionItems. [BR-110]
  const withoutAlt = withoutAltRaw.filter((item) => !outstandingPartialSet.has(item.media_id));

  // Partials after a write sit in withExistingAlt once existing_alt flips true;
  // until then the filter above keeps them out of withoutAlt. [RLSE-04]
  const historyCompletionItems = outstandingPartialIds
    .map((id) => itemsById.get(id))
    .filter((item): item is DescribeRunItem => item !== undefined);
  const overwriteCandidates = withExistingAlt.filter((item) => !outstandingPartialSet.has(item.media_id));

  // Real set difference: only count outstanding ids not already in the safe
  // write set so a stale items query cannot double-count. [BR-110]
  const withoutAltSet = new Set(withoutAlt.map((item) => item.media_id));
  const partialCompletionIds = outstandingPartialIds.filter((id) => !withoutAltSet.has(id));

  const hasApplicable = withoutAlt.length > 0 || overwriteCandidates.length > 0 || outstandingPartialIds.length > 0;
  const selectedOverwrites = overwriteCandidates.filter((item) => overwriteIds.has(item.media_id));
  // Explicit selections (safe + overwrite). Outstanding partials are completed
  // implicitly by the server on the same request — count them in the label. [BR-91]
  const applyCount = withoutAlt.length + selectedOverwrites.length;
  const partialCompletionCount = partialCompletionIds.length;
  const totalWriteCount = applyCount + partialCompletionCount;
  const canApply = totalWriteCount > 0;
  const partialRetryOnly = partialCompletionCount > 0 && applyCount === 0;
  const primaryLabel = partialRetryOnly
    ? sprintf(__('Apply again to complete history for %d', 'alt-context'), partialCompletionCount)
    : withoutAlt.length > 0 && selectedOverwrites.length === 0 && partialCompletionCount === 0
      ? sprintf(__('Apply all %d without alt text', 'alt-context'), withoutAlt.length)
      : sprintf(__('Apply %d descriptions', 'alt-context'), totalWriteCount);

  // Idle "nothing selected" must stay focusable with an announced reason;
  // pending is a genuine busy state and may natively disable. Do not collapse
  // the two into one flag. [BR-105][A11Y-24]
  const nothingSelectedIdle = !canApply && !apply.isPending;
  const applyBusy = apply.isPending;

  const onApply = (): void => {
    if (!canApply || apply.isPending) {
      return;
    }
    apply.mutate(
      selectedOverwrites.map((item) => item.media_id),
      {
        onSuccess: onApplySuccess,
      },
    );
  };

  const resultText = lastResult
    ? buildApplyResultText(lastResult, itemsById, historyRecovered, historyIncompleteIds)
    : '';

  const safePanelHeading =
    withoutAlt.length > 0
      ? sprintf(__('%d descriptions ready to apply', 'alt-context'), withoutAlt.length)
      : historyCompletionItems.length > 0
        ? sprintf(__('%d need history completion', 'alt-context'), historyCompletionItems.length)
        : __('No new descriptions without existing alt text', 'alt-context');

  const safePanelBody =
    withoutAlt.length > 0
      ? __('These images have no alt text yet, so their drafts apply safely.', 'alt-context')
      : historyCompletionItems.length > 0
        ? __(
            'Alt text was already saved for these images. Apply again so they appear in history — this does not overwrite alt text.',
            'alt-context',
          )
        : __('All drafts for this run already have alt text. Check images below to overwrite.', 'alt-context');

  const liveRegion = (
    <div
      className={resultText ? 'acx-dashboard__panel acx-run-apply__result' : undefined}
      role="status"
      aria-live="polite"
      data-testid="acx-run-apply-status"
    >
      {resultText}
    </div>
  );

  return (
    <section className="acx-history acx-run-apply" aria-label={__('Apply run drafts', 'alt-context')}>
      {header}

      {liveRegion}

      {showLoading ? <p>{__('Loading run drafts…', 'alt-context')}</p> : null}

      {preferRetainedOnError ? (
        <div className="notice inline notice-warning" role="alert">
          <p>
            {__('Could not refresh this run’s drafts. Showing saved drafts; they may be out of date.', 'alt-context')}
          </p>
          <button
            type="button"
            className="acx-button acx-button--secondary"
            disabled={itemsQuery.isFetching}
            onClick={() => void itemsQuery.refetch()}
          >
            {__('Retry', 'alt-context')}
          </button>
        </div>
      ) : null}

      {showItemsError ? (
        <section className="acx-dashboard__panel acx-history__panel">
          <h2>{__('Could not load this run’s drafts.', 'alt-context')}</h2>
          <button type="button" className="acx-button acx-button--secondary" onClick={() => void itemsQuery.refetch()}>
            {__('Retry', 'alt-context')}
          </button>
        </section>
      ) : null}

      {showMain ? (
        <>
          {apply.isError ? (
            <div className="acx-error-state" role="alert">
              <span aria-hidden="true">⚠</span> {__('Could not apply the run drafts. Try again.', 'alt-context')}
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
              <EmptyState
                variant={EmptyStateVariant.EMPTY}
                heading={__('No drafts from this run can be applied.', 'alt-context')}
                body={__('Every described item either failed or produced no draft text.', 'alt-context')}
                action={{
                  label: __('Back to Description Runs', 'alt-context'),
                  href: toDescriptionHistory(),
                }}
                headingLevel={2}
              />
            </section>
          ) : (
            <>
              <section
                className="acx-dashboard__panel acx-run-apply__safe"
                aria-label={__('Ready to apply', 'alt-context')}
              >
                <h2>{safePanelHeading}</h2>
                <p>{safePanelBody}</p>
                <ul className="acx-run-apply__list">
                  {withoutAlt.map((item) => (
                    <li key={item.media_id} className="acx-run-apply__item">
                      <span className="acx-run-apply__item-heading">{itemHeading(item)}</span>
                      <span className="acx-run-apply__draft">{item.alt_text_draft}</span>
                      <span className="acx-run-apply__media-id">
                        {sprintf(__('Media %d', 'alt-context'), item.media_id)}
                      </span>
                      {tierBadgeFor(item)}
                      {namingBadgeFor(item)}
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
                        {sprintf(
                          __('Media %1$d — needs history completion (no overwrite)', 'alt-context'),
                          item.media_id,
                        )}
                      </span>
                      {tierBadgeFor(item)}
                      {namingBadgeFor(item)}
                    </li>
                  ))}
                </ul>
                {nothingSelectedIdle ? (
                  <span id={disabledReasonId} className="screen-reader-text">
                    {__('Nothing selected to apply. Check an image below to overwrite its alt text.', 'alt-context')}
                  </span>
                ) : null}
                <button
                  type="button"
                  className="acx-button acx-button--primary"
                  // Busy: native disabled is legitimate (no double-submit).
                  // Idle nothing-selected: aria-disabled only so the reason
                  // stays reachable. [BR-105][A11Y-24]
                  disabled={applyBusy}
                  aria-disabled={nothingSelectedIdle || applyBusy ? true : undefined}
                  aria-describedby={nothingSelectedIdle ? disabledReasonId : undefined}
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
                  <h2>{sprintf(__('%d images already have alt text', 'alt-context'), overwriteCandidates.length)}</h2>
                  <p>
                    {__('Check an image to overwrite its alt text with the new draft when you apply.', 'alt-context')}
                  </p>
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
                        <span className="acx-run-apply__media-id">
                          {sprintf(__('Media %d', 'alt-context'), item.media_id)}
                        </span>
                        {tierBadgeFor(item)}
                        {namingBadgeFor(item)}
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
                    <span>{sprintf(__('Media %1$d — %2$s', 'alt-context'), item.media_id, item.status)}</span>
                    {tierBadgeFor(item)}
                    {namingBadgeFor(item)}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </section>
  );
};

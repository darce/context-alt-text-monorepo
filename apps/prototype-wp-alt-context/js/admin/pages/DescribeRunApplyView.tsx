import React, { useEffect, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { useDescribeRunApply } from '../hooks/useDescribeRunApply';
import type { DescribeRunItem } from '../api/describeApi';

interface DescribeRunApplyViewProps {
  runId: string;
}

const itemHeading = (item: DescribeRunItem): string =>
  item.caption && item.caption.trim() !== ''
    ? item.caption
    : sprintf(__('Media %d', 'alt-context'), item.media_id);

/**
 * INT-01d: the operator's read/apply surface for one completed describe run.
 * Drafts with no existing alt apply behind a single primary bulk action (low
 * friction); drafts that would clobber existing operator alt are bucketed behind
 * an explicit per-item overwrite opt-in and never applied by default. Items with
 * no usable draft (failed/skipped) are listed as informational only. Mirrors the
 * guarded single-image write policy — destructive actions are never the default.
 */
export const DescribeRunApplyView = ({ runId }: DescribeRunApplyViewProps): React.JSX.Element => {
  const { itemsQuery, buckets, apply } = useDescribeRunApply(runId);
  const [overwriteIds, setOverwriteIds] = useState<Set<number>>(new Set());

  // Clear the checked overwrites once a write lands so a second apply cannot
  // re-clobber the same existing alt with a stale selection. (Per-run reset is
  // handled by remounting via `key={runId}` in DescriptionHistoryPage.)
  const applySucceeded = apply.isSuccess;
  useEffect(() => {
    if (applySucceeded) {
      setOverwriteIds(new Set());
    }
  }, [applySucceeded]);

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
      <a className="acx-run-apply__back" href="#/description-history">
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
  const hasApplicable = withoutAlt.length > 0 || withExistingAlt.length > 0;
  const selectedOverwrites = withExistingAlt.filter((item) => overwriteIds.has(item.media_id));
  const applyCount = withoutAlt.length + selectedOverwrites.length;
  const primaryLabel =
    withoutAlt.length > 0 && selectedOverwrites.length === 0
      ? sprintf(__('Apply all %d without alt text', 'alt-context'), withoutAlt.length)
      : sprintf(__('Apply %d descriptions', 'alt-context'), applyCount);

  const onApply = (): void => {
    apply.mutate(selectedOverwrites.map((item) => item.media_id));
  };

  return (
    <section className="acx-history acx-run-apply" aria-label={__('Apply run drafts', 'alt-context')}>
      {header}

      {apply.isSuccess && apply.data ? (
        <div className="acx-dashboard__panel acx-run-apply__result" role="status" aria-live="polite">
          <p>
            {sprintf(__('Applied %d descriptions.', 'alt-context'), apply.data.applied.length)}{' '}
            {apply.data.skipped_existing.length > 0
              ? sprintf(__('Skipped %d with existing alt text.', 'alt-context'), apply.data.skipped_existing.length)
              : ''}{' '}
            {apply.data.skipped_no_draft.length > 0
              ? sprintf(__('%d had no draft.', 'alt-context'), apply.data.skipped_no_draft.length)
              : ''}{' '}
            {apply.data.failed.length > 0
              ? sprintf(__('%d failed to write.', 'alt-context'), apply.data.failed.length)
              : ''}{' '}
            {apply.data.skipped_invalid.length > 0
              ? sprintf(__('%d were not valid attachments.', 'alt-context'), apply.data.skipped_invalid.length)
              : ''}
          </p>
        </div>
      ) : null}

      {apply.isError ? (
        <div className="acx-error-state" role="alert">
          <span aria-hidden="true">⚠</span>{' '}
          {__('Could not apply the run drafts. Try again.', 'alt-context')}
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
            <h2>
              {withoutAlt.length > 0
                ? sprintf(__('%d descriptions ready to apply', 'alt-context'), withoutAlt.length)
                : __('No new descriptions without existing alt text', 'alt-context')}
            </h2>
            <p>{__('These images have no alt text yet, so their drafts apply safely.', 'alt-context')}</p>
            <ul className="acx-run-apply__list">
              {withoutAlt.map((item) => (
                <li key={item.media_id} className="acx-run-apply__item">
                  <span className="acx-run-apply__item-heading">{itemHeading(item)}</span>
                  <span className="acx-run-apply__draft">{item.alt_text_draft}</span>
                  <span className="acx-run-apply__media-id">{sprintf(__('Media %d', 'alt-context'), item.media_id)}</span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="acx-button acx-button--primary"
              disabled={applyCount === 0 || apply.isPending}
              onClick={onApply}
            >
              {apply.isPending ? __('Applying…', 'alt-context') : primaryLabel}
            </button>
          </section>

          {withExistingAlt.length > 0 ? (
            <section
              className="acx-dashboard__panel acx-run-apply__existing"
              aria-label={__('Existing alt text', 'alt-context')}
            >
              <h2>
                {sprintf(__('%d images already have alt text', 'alt-context'), withExistingAlt.length)}
              </h2>
              <p>{__('Check an image to overwrite its alt text with the new draft when you apply.', 'alt-context')}</p>
              <ul className="acx-run-apply__list">
                {withExistingAlt.map((item) => (
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

import React, { useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { __, sprintf } from '@wordpress/i18n';
import { RotateCcw } from 'lucide-react';

import {
  DESCRIPTION_CORRECTION_CODE,
  fetchDescriptionHistory,
  RECOVERY_KIND,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataBooleanField,
  resolveDescribeErrorDataField,
  resolveDescribeErrorMessage,
  type DescriptionHistoryItem,
  type DescriptionHistoryProvenance,
  type DescriptionHistoryResponse,
  type ProvenanceRecoveredFrom,
} from '../api/describeApi';
import { useCorrectMediaAlt } from '../hooks/useCorrectMediaAlt';
import { APP_LINK_PARAMS, parseRunParam } from '../navigation/appLinks';
import { decodeHtmlEntities } from '../utils/decodeHtmlEntities';
import { DescribeRunApplyView } from './DescribeRunApplyView';

const HISTORY_QUERY_KEY = ['description-history'] as const;

const CORRECTION_ERROR_FALLBACK = __('Could not save the alt text. Please try again.', 'alt-context');

/** Surface owner labels for recovery origin — centralised [sr-007]. */
const RECOVERY_SURFACE_LABEL = {
  cli: __('CLI generate', 'alt-context'),
  single_image: __('Single-image describe', 'alt-context'),
} as const;

const getModelLabel = (item: DescriptionHistoryItem): string => {
  const provenance = item.provenance;
  if (!provenance || typeof provenance !== 'object') {
    return __('Unknown model', 'alt-context');
  }

  const modelId = provenance.model_id;
  return typeof modelId === 'string' && modelId.trim() !== '' ? modelId : __('Unknown model', 'alt-context');
};

const getRunStatusLabel = (item: DescriptionHistoryItem): string =>
  typeof item.run_status?.status === 'string' && item.run_status.status.trim() !== ''
    ? item.run_status.status
    : __('Not recorded', 'alt-context');

/**
 * Extract the recovery descriptor when a foreign recovery occurred.
 * none / same_run / missing → null (no operator-visible recovery line).
 */
const getRecoveredFrom = (item: DescriptionHistoryItem): ProvenanceRecoveredFrom | null => {
  const provenance = item.provenance;
  if (!provenance || typeof provenance !== 'object') {
    return null;
  }
  const recovered = (provenance as DescriptionHistoryProvenance).recovered_from;
  if (!recovered || typeof recovered !== 'object') {
    return null;
  }
  if (
    recovered.kind === RECOVERY_KIND.NONE ||
    recovered.kind === RECOVERY_KIND.SAME_RUN ||
    recovered.origin == null ||
    String(recovered.origin).trim() === ''
  ) {
    return null;
  }
  return recovered;
};

/** Operator-facing origin label — never raw JSON [R23-BR-22]. */
const getRecoveryOriginLabel = (recovered: ProvenanceRecoveredFrom): string => {
  const origin = String(recovered.origin ?? '').trim();
  if (recovered.kind === RECOVERY_KIND.SURFACE) {
    if (origin === 'cli') {
      return RECOVERY_SURFACE_LABEL.cli;
    }
    if (origin === 'single_image') {
      return RECOVERY_SURFACE_LABEL.single_image;
    }
  }
  if (recovered.kind === RECOVERY_KIND.RUN) {
    return sprintf(__('Run %s', 'alt-context'), origin);
  }
  if (recovered.kind === RECOVERY_KIND.UNKNOWN) {
    return sprintf(__('Unknown owner (%s)', 'alt-context'), origin);
  }
  return origin;
};

/** Stored history alts are entity-encoded; decode once at the read boundary (BR-140). */
const decodeStoredAltText = (stored: string | null | undefined): string =>
  stored == null || stored === '' ? (stored ?? '') : decodeHtmlEntities(stored);

const getDraftValue = (drafts: Record<number, string>, item: DescriptionHistoryItem): string =>
  // Operator draft is already plain text; fall back to decoded stored current alt.
  drafts[item.media_id] ?? decodeStoredAltText(item.current_alt_text);

const itemMatchesSearch = (item: DescriptionHistoryItem, query: string): boolean => {
  if (query === '') {
    return true;
  }

  // Search the decoded forms so an operator query for `<=` matches displayed text.
  const fields = [
    item.title,
    item.mime_type,
    decodeStoredAltText(item.current_alt_text),
    decodeStoredAltText(item.generated_alt_text),
    String(item.media_id),
    getModelLabel(item),
    getRunStatusLabel(item),
  ];

  return fields.some((field) => field.toLowerCase().includes(query));
};

const clearMediaIdEntry = <T,>(current: Record<number, T>, mediaId: number): Record<number, T> => {
  if (!(mediaId in current)) {
    return current;
  }
  const next = { ...current };
  delete next[mediaId];
  return next;
};

export const DescriptionHistoryPage = (): React.JSX.Element => {
  const [searchParams] = useSearchParams();
  const runId = parseRunParam(searchParams.get(APP_LINK_PARAMS.run));

  // A `?run=<id>` deep-link (from the workbench after a bulk run) switches the
  // page into the run-scoped apply surface; otherwise show the full history.
  if (runId !== null) {
    // `key={runId}` remounts on a run switch so overwrite selection starts empty
    // for each run and cannot carry a stale checked overwrite across deep links.
    return <DescribeRunApplyView key={runId} runId={runId} />;
  }

  return <DescriptionHistoryList />;
};

const DescriptionHistoryList = (): React.JSX.Element => {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  // Per-mediaId pending map: a scalar savingId is overwritten when a second row
  // starts saving, so concurrent (or sequential) saves would mis-report which
  // row is busy. Errors use the same shape for the same reason [RLSE-05].
  const [savingIds, setSavingIds] = useState<Record<number, true>>({});
  // Synchronous mirror of savingIds for the in-flight guard [BR-81]. React state
  // alone is a render-time snapshot; a second same-tick call would still see the
  // pre-update map. The ref is written before mutate and cleared with the state.
  const savingIdsRef = useRef<Record<number, true>>({});
  // Durable per-row correction failures: the shared useMutation resets isError/
  // variables on the next mutate, which would unmount an earlier row's alert
  // the moment another row starts saving [RLSE-05].
  const [correctionErrors, setCorrectionErrors] = useState<Record<number, string>>({});
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const clearSavingId = (mediaId: number): void => {
    savingIdsRef.current = clearMediaIdEntry(savingIdsRef.current, mediaId);
    setSavingIds((current) => clearMediaIdEntry(current, mediaId));
  };

  const historyQuery = useQuery({
    queryKey: HISTORY_QUERY_KEY,
    queryFn: () => fetchDescriptionHistory({ limit: 50, offset: 0 }),
  });

  // Shared correction contract: endpoint call, workbench row patch (altText +
  // status), full-success stats refresh, and partial workbench reconcile from
  // server-reported stored_alt_text [WBUX-5-BR-75]. Page-specific history cache
  // patch and per-row state ride on per-call mutate callbacks — RQ runs both
  // the hook-level and the call-level handlers (verified against v5.100.5).
  const correctionMutation = useCorrectMediaAlt();

  const items = useMemo(() => historyQuery.data?.items ?? [], [historyQuery.data]);
  const statusOptions = useMemo(
    () =>
      Array.from(new Set(items.map((item) => getRunStatusLabel(item)).filter((status) => status !== ''))).sort((a, b) =>
        a.localeCompare(b),
      ),
    [items],
  );
  const filteredItems = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return items.filter((item) => {
      const matchesStatus = statusFilter === 'all' || getRunStatusLabel(item) === statusFilter;
      return matchesStatus && itemMatchesSearch(item, query);
    });
  }, [items, searchQuery, statusFilter]);

  const saveCorrection = (item: DescriptionHistoryItem): void => {
    const mediaId = item.media_id;
    // Presence guard, not a refcount: a second concurrent write to one media id
    // is impossible. Read from the ref (updated synchronously below) so a
    // same-tick second call cannot miss a busy flag still queued in setState [BR-81].
    if (savingIdsRef.current[mediaId]) {
      return;
    }
    const altText = getDraftValue(drafts, item).trim();
    savingIdsRef.current = { ...savingIdsRef.current, [mediaId]: true };
    setSavingIds((current) => ({ ...current, [mediaId]: true }));
    // Clear this row's prior error on re-attempt so a stale alert does not
    // linger while the new request is in flight; other rows' errors stay.
    // Refused starts never reach here — they must not clear correctionErrors.
    setCorrectionErrors((current) => clearMediaIdEntry(current, mediaId));
    correctionMutation.mutate(
      { mediaId, altText },
      {
        // History-only side effects. Workbench patch + invalidateMediaStats are
        // already handled by useCorrectMediaAlt — do not double-invalidate.
        onSuccess: (updatedItem) => {
          queryClient.setQueryData<DescriptionHistoryResponse>(HISTORY_QUERY_KEY, (current) => {
            if (!current) {
              return { total: 1, items: [updatedItem] };
            }

            return {
              ...current,
              items: current.items.map((row) => (row.media_id === updatedItem.media_id ? updatedItem : row)),
            };
          });
          setDrafts((current) => clearMediaIdEntry(current, updatedItem.media_id));
          clearSavingId(updatedItem.media_id);
          setCorrectionErrors((current) => clearMediaIdEntry(current, updatedItem.media_id));
        },
        // Keep the draft: the operator's text is the only copy on a failed write.
        // Surface the server message (or localized fallback) on the failed row so a
        // 500 partial/total failure is never silent [RLSE-05][A11Y-21].
        // Errors live in correctionErrors by mediaId so a later row's mutate cannot
        // erase an earlier unread failure. Shared useMutation would reset isError
        // on the next mutate — that is why this map stays page-local [RLSE-05].
        onError: (error, variables) => {
          // Alert first and always — partial or total, with or without stored_alt_text.
          // The operator is never left uninformed [RLSE-05][A11Y-21].
          const message = resolveDescribeErrorMessage(error, CORRECTION_ERROR_FALLBACK);
          setCorrectionErrors((current) => ({
            ...current,
            [variables.mediaId]: message,
          }));
          clearSavingId(variables.mediaId);

          // Partial: alt is already in storage. Patch history current_alt_text from
          // the server-reported stored value only — never from variables.altText,
          // which may still carry markup/whitespace sanitize_text_field stripped
          // ([rg-015]). Workbench reconcile is the hook's onError. If
          // stored_alt_text is absent, leave history cache alone (stale-but-real).
          // Total failure must not touch any cache [RLSE-04]. Alert still shows either way.
          if (resolveDescribeErrorCode(error) !== DESCRIPTION_CORRECTION_CODE.PARTIAL) {
            return;
          }
          const storedAltText = resolveDescribeErrorDataField(error, 'stored_alt_text');
          if (storedAltText === null) {
            return;
          }
          // is_decorative is optional on older PARTIAL payloads; when present it
          // is server truth and must land on the cached history row [A-03][rg-015].
          const storedIsDecorative = resolveDescribeErrorDataBooleanField(error, 'is_decorative');
          queryClient.setQueryData<DescriptionHistoryResponse>(HISTORY_QUERY_KEY, (current) => {
            if (!current) {
              return current;
            }
            return {
              ...current,
              items: current.items.map((row) =>
                row.media_id === variables.mediaId
                  ? {
                      ...row,
                      current_alt_text: storedAltText,
                      ...(storedIsDecorative !== null
                        ? { is_decorative: storedIsDecorative }
                        : {}),
                    }
                  : row,
              ),
            };
          });
        },
      },
    );
  };

  if (historyQuery.isLoading) {
    return (
      <section className="acx-history" aria-labelledby="acx-history-title">
        <h1 id="acx-history-title" className="acx-dashboard__title">
          {__('Description Runs', 'alt-context')}
        </h1>
        <p>{__('Loading description history...', 'alt-context')}</p>
      </section>
    );
  }

  if (historyQuery.isError) {
    return (
      <section className="acx-history" aria-labelledby="acx-history-title">
        <header className="acx-history__hero">
          <p className="acx-dashboard__eyebrow">{__('Review', 'alt-context')}</p>
          <h1 id="acx-history-title" className="acx-dashboard__title">
            {__('Description Runs', 'alt-context')}
          </h1>
        </header>
        <section className="acx-dashboard__panel acx-history__panel">
          <h2>{__('Could not load description history.', 'alt-context')}</h2>
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={() => void historyQuery.refetch()}
          >
            {__('Retry', 'alt-context')}
          </button>
        </section>
      </section>
    );
  }

  return (
    <section className="acx-history" aria-labelledby="acx-history-title">
      <header className="acx-history__hero">
        <p className="acx-dashboard__eyebrow">{__('Review', 'alt-context')}</p>
        <h1 id="acx-history-title" className="acx-dashboard__title">
          {__('Description Runs', 'alt-context')}
        </h1>
        <p className="acx-dashboard__subtitle">
          {__('Review generated alt text, provenance, and human corrections in one workspace.', 'alt-context')}
        </p>
      </header>

      {items.length === 0 ? (
        <section className="acx-dashboard__panel acx-history__panel">
          <h2>{__('No generated descriptions yet.', 'alt-context')}</h2>
        </section>
      ) : (
        <>
          <section className="acx-dashboard__panel acx-history__filters" aria-label={__('History filters', 'alt-context')}>
            <label>
              <span>{__('Search descriptions', 'alt-context')}</span>
              <input
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </label>
            <label>
              <span>{__('Run status filter', 'alt-context')}</span>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">{__('All statuses', 'alt-context')}</option>
                {statusOptions.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </label>
          </section>
          {filteredItems.length === 0 ? (
            <section className="acx-dashboard__panel acx-history__panel">
              <h2>{__('No history items match the current filters.', 'alt-context')}</h2>
            </section>
          ) : null}
          <div className="acx-history__list">
            {filteredItems.map((item) => {
              const draft = getDraftValue(drafts, item);
              const isSaving = Boolean(savingIds[item.media_id]);
              const rowErrorMessage = correctionErrors[item.media_id] ?? null;
              const recovered = getRecoveredFrom(item);
              const recoveryOriginLabel = recovered ? getRecoveryOriginLabel(recovered) : null;

              return (
                <article key={item.media_id} className="acx-dashboard__panel acx-history__item">
                  <header className="acx-history__item-header">
                    <div>
                      <h2>{item.title}</h2>
                      <p>{sprintf(__('Media ID %d - %s', 'alt-context'), item.media_id, item.mime_type)}</p>
                    </div>
                    {item.human_edit ? <span className="acx-history__badge">{__('Human edited', 'alt-context')}</span> : null}
                  </header>

                  <div className="acx-history__columns">
                    <section>
                      <h3>{__('Generated draft', 'alt-context')}</h3>
                      <p className="acx-history__text">
                        {item.generated_alt_text
                          ? decodeHtmlEntities(item.generated_alt_text)
                          : __('No draft recorded.', 'alt-context')}
                      </p>
                    </section>
                    <section>
                      <h3>{__('Current alt text', 'alt-context')}</h3>
                      <p className="acx-history__text">
                        {item.current_alt_text
                          ? decodeHtmlEntities(item.current_alt_text)
                          : __('No alt text saved.', 'alt-context')}
                      </p>
                    </section>
                  </div>

                  <dl className="acx-history__meta">
                    <div>
                      <dt>{__('Model', 'alt-context')}</dt>
                      <dd>{getModelLabel(item)}</dd>
                    </div>
                    <div>
                      <dt>{__('Run status', 'alt-context')}</dt>
                      <dd>{getRunStatusLabel(item)}</dd>
                    </div>
                    {recovered && recoveryOriginLabel !== null ? (
                      <div data-testid="acx-history-recovery">
                        <dt>{__('Recovery', 'alt-context')}</dt>
                        <dd className="acx-history__recovery">
                          <span
                            className="acx-history__recovery-icon"
                            aria-hidden="true"
                            data-testid="acx-history-recovery-icon"
                          >
                            <RotateCcw size={14} />
                          </span>
                          <span data-testid="acx-history-recovery-origin">
                            {sprintf(__('Recovered from %s', 'alt-context'), recoveryOriginLabel)}
                          </span>
                        </dd>
                      </div>
                    ) : null}
                  </dl>

                  <label className="acx-history__correction">
                    <span>{sprintf(__('Alt text correction for %s', 'alt-context'), item.title)}</span>
                    <textarea
                      value={draft}
                      onChange={(event) =>
                        setDrafts((current) => ({
                          ...current,
                          [item.media_id]: event.target.value,
                        }))
                      }
                    />
                  </label>
                  {rowErrorMessage !== null ? (
                    <div className="acx-history__correction-error" role="alert">
                      {rowErrorMessage}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    className="acx-button acx-button--primary"
                    disabled={isSaving || draft.trim() === ''}
                    onClick={() => saveCorrection(item)}
                  >
                    {isSaving
                      ? __('Saving...', 'alt-context')
                      : sprintf(__('Save correction for %s', 'alt-context'), item.title)}
                  </button>
                </article>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
};

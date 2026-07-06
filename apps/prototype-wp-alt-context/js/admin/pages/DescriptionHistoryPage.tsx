import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import {
  correctDescriptionHistoryItem,
  fetchDescriptionHistory,
  type DescriptionHistoryItem,
  type DescriptionHistoryResponse,
} from '../api/describeApi';

const HISTORY_QUERY_KEY = ['description-history'] as const;

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

const getDraftValue = (drafts: Record<number, string>, item: DescriptionHistoryItem): string =>
  drafts[item.media_id] ?? item.current_alt_text ?? '';

const itemMatchesSearch = (item: DescriptionHistoryItem, query: string): boolean => {
  if (query === '') {
    return true;
  }

  const fields = [
    item.title,
    item.mime_type,
    item.current_alt_text,
    item.generated_alt_text,
    String(item.media_id),
    getModelLabel(item),
    getRunStatusLabel(item),
  ];

  return fields.some((field) => field.toLowerCase().includes(query));
};

export const DescriptionHistoryPage = (): React.JSX.Element => {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const historyQuery = useQuery({
    queryKey: HISTORY_QUERY_KEY,
    queryFn: () => fetchDescriptionHistory({ limit: 50, offset: 0 }),
  });

  const correctionMutation = useMutation({
    mutationFn: ({ mediaId, altText }: { mediaId: number; altText: string }) =>
      correctDescriptionHistoryItem(mediaId, altText),
    onSuccess: (updatedItem) => {
      queryClient.setQueryData<DescriptionHistoryResponse>(HISTORY_QUERY_KEY, (current) => {
        if (!current) {
          return { total: 1, items: [updatedItem] };
        }

        return {
          ...current,
          items: current.items.map((item) => (item.media_id === updatedItem.media_id ? updatedItem : item)),
        };
      });
      setDrafts((current) => {
        const next = { ...current };
        delete next[updatedItem.media_id];
        return next;
      });
      setSavingId(null);
    },
    onError: () => {
      setSavingId(null);
    },
  });

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
    const altText = getDraftValue(drafts, item).trim();
    setSavingId(item.media_id);
    correctionMutation.mutate({ mediaId: item.media_id, altText });
  };

  if (historyQuery.isLoading) {
    return (
      <section className="acx-history" aria-labelledby="acx-history-title">
        <h1 id="acx-history-title" className="acx-dashboard__title">
          {__('Description Review History', 'alt-context')}
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
            {__('Description Review History', 'alt-context')}
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
          {__('Description Review History', 'alt-context')}
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
              const isSaving = savingId === item.media_id && correctionMutation.isPending;

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
                      <p className="acx-history__text">{item.generated_alt_text || __('No draft recorded.', 'alt-context')}</p>
                    </section>
                    <section>
                      <h3>{__('Current alt text', 'alt-context')}</h3>
                      <p className="acx-history__text">{item.current_alt_text || __('No alt text saved.', 'alt-context')}</p>
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

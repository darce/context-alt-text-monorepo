import React, { useEffect, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
import type { RosterEntry } from '../../api/rosterApi';
import { RosterEntriesTable } from './RosterEntriesTable';
import { useDebouncedValue } from './hooks/useDebouncedValue';
import { useCreatePerson } from '../../hooks/useRosterHooks';
import { Filter, UserPlus, Plus, Users, X } from 'lucide-react';
import { toWorkbench } from '../../navigation/appLinks';
import { isHumanLabeledTarget } from '../workbench/identity-clusters/suggestionProjection';

const RESERVED_LABEL_MESSAGE = __(
  'This label format is reserved for automatic cluster IDs. Choose a descriptive name.',
  'alt-context',
);

type QueueFilterId = RosterEntry['queue_memberships'][number];

interface QueueFilterDetails {
  badge: string;
  status: string;
  empty: string;
}

interface QueueReviewRoute {
  href: string;
  label: string;
}

const WORKBENCH_SCAN_ROUTE = toWorkbench({ tab: 'scan' });

/** URL key for directory text search — same short `s` convention as workbench. */
const SEARCH_PARAM = 's';

/** Quiet period before the search summary is copied into role=status [ROSTER-W-03]. */
export const SEARCH_STATUS_DEBOUNCE_MS = 300;

const isQueueFilterId = (value: string | null): value is QueueFilterId =>
  value === 'singleton-proposals' || value === 'hard-examples' || value === 'needs-confirmation-after-merge';

const getQueueFilterDetails = (queueFilter: QueueFilterId | null): QueueFilterDetails | null => {
  switch (queueFilter) {
    case 'singleton-proposals':
      return {
        badge: __('Filtered: Singleton proposals', 'alt-context'),
        status: __('Showing singleton proposals queue only.', 'alt-context'),
        empty: __('No people in singleton proposals queue.', 'alt-context'),
      };
    case 'hard-examples':
      return {
        badge: __('Filtered: Hard examples', 'alt-context'),
        status: __('Showing hard examples queue only.', 'alt-context'),
        empty: __('No people in hard examples queue.', 'alt-context'),
      };
    case 'needs-confirmation-after-merge':
      return {
        badge: __('Filtered: Needs confirmation after merge', 'alt-context'),
        status: __('Showing needs confirmation after merge queue only.', 'alt-context'),
        empty: __('No people in needs confirmation after merge queue.', 'alt-context'),
      };
    default:
      return null;
  }
};

const getQueueReviewRoute = (queueFilter: QueueFilterId | null): QueueReviewRoute | null => {
  switch (queueFilter) {
    case 'singleton-proposals':
      return {
        href: WORKBENCH_SCAN_ROUTE,
        label: __('Review singleton proposals in Workbench', 'alt-context'),
      };
    case 'needs-confirmation-after-merge':
      return {
        href: WORKBENCH_SCAN_ROUTE,
        label: __('Review merge confirmations in Workbench', 'alt-context'),
      };
    default:
      return null;
  }
};

const getQueueActionNotice = (queueFilter: QueueFilterId | null): string | null => {
  if (queueFilter === 'hard-examples') {
    return __(
      'Hard-examples review actions stay unavailable here until the dedicated review contract lands.',
      'alt-context',
    );
  }

  return null;
};

/**
 * Case-insensitive substring match over name and tags.
 * Unnamed people (`name === ''`) never match a non-empty name fragment; they
 * can still match via tags.
 */
const entryMatchesSearch = (entry: RosterEntry, normalizedQuery: string): boolean => {
  if (normalizedQuery === '') {
    return true;
  }
  if (entry.name.toLowerCase().includes(normalizedQuery)) {
    return true;
  }
  return entry.tags.some((tag) => tag.toLowerCase().includes(normalizedQuery));
};

export interface RosterEntriesQuery {
  isLoading: boolean;
  isError: boolean;
  data?: RosterEntry[];
  refetch: () => unknown;
}

export interface RosterEntriesSectionProps {
  query: RosterEntriesQuery;
  routeNotice?: string | null;
}

export const RosterEntriesSection = ({ query, routeNotice = null }: RosterEntriesSectionProps): React.JSX.Element => {
  const [isAdding, setIsAdding] = useState(false);
  const [newName, setNewName] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [createHiddenBySearchNotice, setCreateHiddenBySearchNotice] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const createPerson = useCreatePerson();
  const personFilter = searchParams.get('personFilter');
  const queueParam = searchParams.get('queue');
  const queueFilter: QueueFilterId | null = isQueueFilterId(queueParam) ? queueParam : null;
  const queueFilterDetails = getQueueFilterDetails(queueFilter);
  const isUnassignedFilter = personFilter === 'unassigned';
  // URL is the shareable source of truth; local state keeps keystrokes from racing
  // the controlled input against async search-param writes.
  const searchFromUrl = searchParams.get(SEARCH_PARAM) ?? '';
  const [searchQuery, setSearchQuery] = useState(searchFromUrl);
  useEffect(() => {
    setSearchQuery(searchFromUrl);
  }, [searchFromUrl]);
  const trimmedSearch = searchQuery.trim();
  const normalizedSearch = trimmedSearch.toLowerCase();
  const hasActiveSearch = normalizedSearch.length > 0;
  const entries = query.data ?? [];
  const visibleEntries = entries.filter((entry) => {
    if (isUnassignedFilter && entry.cluster_count !== 0) {
      return false;
    }
    // Boundary read: create_person / update_person REST bodies omit
    // queue_memberships; treat absent as empty (same as derivePersonState).
    const memberships = Array.isArray(entry.queue_memberships) ? entry.queue_memberships : [];
    if (queueFilter !== null && !memberships.includes(queueFilter)) {
      return false;
    }
    if (!entryMatchesSearch(entry, normalizedSearch)) {
      return false;
    }
    return true;
  });
  const hasCategoricalFilter = queueFilterDetails !== null || isUnassignedFilter;
  const activeFilterBadge =
    queueFilterDetails !== null
      ? queueFilterDetails.badge
      : isUnassignedFilter
        ? __('Filtered: Unassigned', 'alt-context')
        : null;
  const activeFilterStatus =
    queueFilterDetails !== null
      ? queueFilterDetails.status
      : isUnassignedFilter
        ? __('Showing unassigned people only.', 'alt-context')
        : null;
  const emptyFilterMessage =
    queueFilterDetails !== null
      ? queueFilterDetails.empty
      : isUnassignedFilter
        ? __('No unassigned people found.', 'alt-context')
        : null;
  const queueReviewRoute = getQueueReviewRoute(queueFilter);
  const queueActionNotice = getQueueActionNotice(queueFilter);

  /**
   * Extend the existing filter status surface with a search result summary so
   * SR users hear one status region (no second live region / A11Y-21). Match
   * counts debounce; empty-search / empty-filter copy joins the same region
   * immediately [E21-19-REV1-02].
   */
  const searchStatus =
    hasActiveSearch && visibleEntries.length > 0
      ? sprintf(
          /* translators: 1: match count, 2: search query */
          __('Showing %1$d matching “%2$s”.', 'alt-context'),
          visibleEntries.length,
          trimmedSearch,
        )
      : null;
  // Filter/table stay live; only non-null status-region rewrites are delayed
  // [ROSTER-W-03]. Transition to null flushes immediately [E21-19-REV1-01].
  const announcedSearchStatus = useDebouncedValue(searchStatus, SEARCH_STATUS_DEBOUNCE_MS);

  const emptySearchMessage = hasActiveSearch
    ? hasCategoricalFilter
      ? sprintf(
          /* translators: %s: search query */
          __('No people match “%s” within the current filter.', 'alt-context'),
          trimmedSearch,
        )
      : sprintf(
          /* translators: %s: search query */
          __('No people match “%s”.', 'alt-context'),
          trimmedSearch,
        )
    : null;

  const clearFilter = () => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete('personFilter');
        next.delete('queue');
        next.set('tab', 'entries');
        return next;
      },
      { replace: true },
    );
  };

  const clearSearch = () => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete(SEARCH_PARAM);
        next.set('tab', 'entries');
        return next;
      },
      { replace: true },
    );
    setCreateHiddenBySearchNotice(null);
  };

  const handleSearchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setSearchQuery(value);
    setCreateHiddenBySearchNotice(null);
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value === '') {
          next.delete(SEARCH_PARAM);
        } else {
          next.set(SEARCH_PARAM, value);
        }
        next.set('tab', 'entries');
        return next;
      },
      { replace: true },
    );
  };

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) {
      return;
    }

    const submittedName = newName.trim();
    // BR-60: reject reserved machine-shaped person names before create.
    if (!isHumanLabeledTarget(submittedName)) {
      setNameError(RESERVED_LABEL_MESSAGE);
      return;
    }
    setNameError(null);
    createPerson.mutate(
      { name: submittedName },
      {
        onSuccess: () => {
          setNewName('');
          setIsAdding(false);
          setNameError(null);
          // A successful create that vanishes behind an active search reads as
          // a failed add. Surface the recovery when the new name would not match.
          if (hasActiveSearch && !submittedName.toLowerCase().includes(normalizedSearch)) {
            setCreateHiddenBySearchNotice(
              sprintf(
                /* translators: 1: person name, 2: search query */
                __(
                  'Created “%1$s”. They are hidden by the current search for “%2$s” — clear search to see them.',
                  'alt-context',
                ),
                submittedName,
                trimmedSearch,
              ),
            );
          } else {
            setCreateHiddenBySearchNotice(null);
          }
        },
      },
    );
  };

  // True zero: roster genuinely has no people. Search must not promote this
  // into the search-empty copy, and search-empty must never render onboarding.
  const isTrueZeroState = !query.isLoading && !query.isError && entries.length === 0 && emptyFilterMessage === null;

  const isEmptySearchResult =
    !query.isLoading &&
    !query.isError &&
    !isTrueZeroState &&
    entries.length > 0 &&
    visibleEntries.length === 0 &&
    hasActiveSearch;

  const isEmptyFilterResult =
    !query.isLoading &&
    !query.isError &&
    emptyFilterMessage !== null &&
    visibleEntries.length === 0 &&
    !hasActiveSearch;

  const immediateEmptyStatus =
    isEmptySearchResult && emptySearchMessage !== null
      ? emptySearchMessage
      : isEmptyFilterResult
        ? emptyFilterMessage
        : null;
  const statusLines = [activeFilterStatus, announcedSearchStatus, immediateEmptyStatus].filter(
    (line): line is string => line !== null,
  );

  return (
    <div className="acx-roster-section" data-testid="roster-entries-section">
      <header className="acx-roster-section__header">
        <div className="acx-roster-section__title-group">
          <h2>{__('People', 'alt-context')}</h2>
          {activeFilterBadge && (
            <span className="acx-roster-section__filter-badge" data-testid="roster-filter-badge">
              <Filter size={12} aria-hidden="true" data-testid="roster-filter-badge-icon" />
              {activeFilterBadge}
            </span>
          )}
        </div>
        {!isAdding && (
          <button
            type="button"
            className="acx-button acx-button--primary"
            onClick={() => {
              setNameError(null);
              setIsAdding(true);
            }}
          >
            <UserPlus size={16} aria-hidden="true" />
            {__('Add Person', 'alt-context')}
          </button>
        )}
      </header>

      {!query.isLoading && !query.isError && !isTrueZeroState && (
        <div className="acx-form-group">
          <label htmlFor="acx-roster-people-search">{__('Search people', 'alt-context')}</label>
          <input
            id="acx-roster-people-search"
            type="search"
            className="acx-input"
            value={searchQuery}
            onChange={handleSearchChange}
            placeholder={__('Search by name or tag…', 'alt-context')}
          />
        </div>
      )}

      {query.isLoading && <p>{__('Loading roster entries…', 'alt-context')}</p>}

      {query.isError && (
        <div className="acx-error-state" role="status">
          <p>{__('Unable to load roster entries.', 'alt-context')}</p>
          <button type="button" className="acx-button acx-button--secondary" onClick={() => void query.refetch()}>
            {__('Retry', 'alt-context')}
          </button>
        </div>
      )}

      {statusLines.length > 0 && (
        <div className="acx-roster-section__filter" role="status">
          {statusLines.map((line) => (
            <p key={line}>{line}</p>
          ))}
          {queueReviewRoute && (
            <a href={queueReviewRoute.href} className="acx-link-button">
              {queueReviewRoute.label}
            </a>
          )}
          {queueActionNotice && <p>{queueActionNotice}</p>}
          {/* Recovery buttons: when search is empty the empty-search panel owns them. */}
          {!isEmptySearchResult && hasCategoricalFilter && (
            <button type="button" className="acx-link-button" onClick={clearFilter}>
              {__('Clear filter', 'alt-context')}
            </button>
          )}
          {!isEmptySearchResult && hasActiveSearch && (
            <button type="button" className="acx-link-button" onClick={clearSearch}>
              {__('Clear search', 'alt-context')}
            </button>
          )}
        </div>
      )}

      {routeNotice && (
        <div className="acx-roster-section__filter" role="status">
          <p>{routeNotice}</p>
        </div>
      )}

      {createHiddenBySearchNotice && (
        <div className="acx-roster-section__filter" role="status">
          <p>{createHiddenBySearchNotice}</p>
          <button type="button" className="acx-link-button" onClick={clearSearch}>
            {__('Clear search', 'alt-context')}
          </button>
        </div>
      )}

      {isAdding && (
        <form className="acx-roster-section__add-form" onSubmit={handleAdd}>
          <div className="acx-form-group">
            <input
              type="text"
              className="acx-input"
              placeholder={__('Full Name', 'alt-context')}
              value={newName}
              onChange={(e) => {
                setNewName(e.target.value);
                if (nameError) {
                  setNameError(null);
                }
              }}
              disabled={createPerson.isPending}
              autoFocus
              aria-invalid={nameError ? true : undefined}
              aria-describedby={nameError ? 'acx-roster-add-name-error' : undefined}
            />
            {nameError && (
              <p
                id="acx-roster-add-name-error"
                className="acx-roster-section__name-error"
                role="alert"
              >
                {nameError}
              </p>
            )}
          </div>
          <div className="acx-form-actions">
            <button
              type="submit"
              className="acx-button acx-button--primary"
              disabled={createPerson.isPending || !newName.trim()}
            >
              <Plus size={16} aria-hidden="true" />
              {__('Create', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => {
                setNameError(null);
                setIsAdding(false);
              }}
              disabled={createPerson.isPending}
            >
              <X size={16} aria-hidden="true" />
              {__('Cancel', 'alt-context')}
            </button>
          </div>
        </form>
      )}

      {!query.isLoading &&
        !query.isError &&
        (isTrueZeroState ? (
          <div
            className="acx-roster-section__empty"
            data-testid="roster-zero-state"
            role="status"
            aria-live="polite"
          >
            <span className="acx-roster-section__empty-icon" aria-hidden="true">
              <Users size={24} />
            </span>
            <h3 className="acx-roster-section__empty-title">{__('No people yet', 'alt-context')}</h3>
            <p className="acx-roster-section__empty-message">
              {__('Add someone manually or run a scan to discover faces from your media library.', 'alt-context')}
            </p>
            <div className="acx-roster-section__empty-actions">
              {!isAdding && (
                <button type="button" className="acx-button acx-button--primary" onClick={() => setIsAdding(true)}>
                  <UserPlus size={16} aria-hidden="true" />
                  {__('Add Person', 'alt-context')}
                </button>
              )}
              <a href={WORKBENCH_SCAN_ROUTE} className="acx-link-button">
                {__('Run a scan in Workbench', 'alt-context')}
              </a>
            </div>
          </div>
        ) : isEmptySearchResult && emptySearchMessage !== null ? (
          <div className="acx-roster-section__filter" data-testid="roster-search-empty">
            <button type="button" className="acx-link-button" onClick={clearSearch}>
              {__('Clear search', 'alt-context')}
            </button>
            {hasCategoricalFilter && (
              <button type="button" className="acx-link-button" onClick={clearFilter}>
                {__('Clear filter', 'alt-context')}
              </button>
            )}
          </div>
        ) : isEmptyFilterResult ? null : (
          <RosterEntriesTable entries={visibleEntries} />
        ))}
    </div>
  );
};

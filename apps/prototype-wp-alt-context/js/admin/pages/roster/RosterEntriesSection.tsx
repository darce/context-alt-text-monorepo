import React, { useState } from 'react';
import { __ } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
import type { RosterEntry } from '../../api/rosterApi';
import { RosterEntriesTable } from './RosterEntriesTable';
import { useCreatePerson } from '../../hooks/useRosterHooks';
import { Filter, UserPlus, Plus, Users, X } from 'lucide-react';

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

const WORKBENCH_SCAN_ROUTE = '#/workbench?tab=scan';

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
  const [searchParams, setSearchParams] = useSearchParams();
  const createPerson = useCreatePerson();
  const personFilter = searchParams.get('personFilter');
  const queueParam = searchParams.get('queue');
  const queueFilter: QueueFilterId | null = isQueueFilterId(queueParam) ? queueParam : null;
  const queueFilterDetails = getQueueFilterDetails(queueFilter);
  const isUnassignedFilter = personFilter === 'unassigned';
  const entries = query.data ?? [];
  const visibleEntries = entries.filter((entry) => {
    if (isUnassignedFilter && entry.cluster_count !== 0) {
      return false;
    }
    if (queueFilter !== null && !entry.queue_memberships.includes(queueFilter)) {
      return false;
    }
    return true;
  });
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

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) {
      return;
    }

    createPerson.mutate(
      { name: newName.trim() },
      {
        onSuccess: () => {
          setNewName('');
          setIsAdding(false);
        },
      },
    );
  };

  const isTrueZeroState = !query.isLoading && !query.isError && entries.length === 0 && emptyFilterMessage === null;

  return (
    <div className="acx-roster-section" data-testid="roster-entries-section">
      <header className="acx-roster-section__header">
        <div className="acx-roster-section__title-group">
          <h2>{__('Managed Identities', 'alt-context')}</h2>
          {activeFilterBadge && (
            <span className="acx-roster-section__filter-badge" data-testid="roster-filter-badge">
              <Filter size={12} aria-hidden="true" data-testid="roster-filter-badge-icon" />
              {activeFilterBadge}
            </span>
          )}
        </div>
        {!isAdding && (
          <button type="button" className="acx-button acx-button--primary" onClick={() => setIsAdding(true)}>
            <UserPlus size={16} aria-hidden="true" />
            {__('Add Person', 'alt-context')}
          </button>
        )}
      </header>

      {query.isLoading && <p>{__('Loading roster entries…', 'alt-context')}</p>}

      {query.isError && (
        <div className="acx-error-state" role="status">
          <p>{__('Unable to load roster entries.', 'alt-context')}</p>
          <button type="button" className="acx-button acx-button--secondary" onClick={() => void query.refetch()}>
            {__('Retry', 'alt-context')}
          </button>
        </div>
      )}

      {activeFilterStatus && (
        <div className="acx-roster-section__filter" role="status">
          <p>{activeFilterStatus}</p>
          {queueReviewRoute && (
            <a href={queueReviewRoute.href} className="acx-link-button">
              {queueReviewRoute.label}
            </a>
          )}
          {queueActionNotice && <p>{queueActionNotice}</p>}
          <button type="button" className="acx-link-button" onClick={clearFilter}>
            {__('Clear filter', 'alt-context')}
          </button>
        </div>
      )}

      {routeNotice && (
        <div className="acx-roster-section__filter" role="status">
          <p>{routeNotice}</p>
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
              onChange={(e) => setNewName(e.target.value)}
              disabled={createPerson.isPending}
              autoFocus
            />
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
              onClick={() => setIsAdding(false)}
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
        ) : emptyFilterMessage && visibleEntries.length === 0 ? (
          <p>{emptyFilterMessage}</p>
        ) : (
          <RosterEntriesTable entries={visibleEntries} />
        ))}
    </div>
  );
};

import React, { useState } from 'react';
import { __ } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
import type { RosterEntry } from '../../api/rosterApi';
import { RosterEntriesTable } from './RosterEntriesTable';
import { useCreatePerson } from '../../hooks/useRosterHooks';
import { UserPlus, Plus, X } from 'lucide-react';

type QueueFilterId = RosterEntry['queue_memberships'][number];

const WORKBENCH_SCAN_ROUTE = '#/workbench?tab=scan';

const QUEUE_FILTERS: Record<QueueFilterId, { badge: string; status: string; empty: string }> = {
  'singleton-proposals': {
    badge: __('Filtered: Singleton proposals', 'alt-context'),
    status: __('Showing singleton proposals queue only.', 'alt-context'),
    empty: __('No people in singleton proposals queue.', 'alt-context'),
  },
  'hard-examples': {
    badge: __('Filtered: Hard examples', 'alt-context'),
    status: __('Showing hard examples queue only.', 'alt-context'),
    empty: __('No people in hard examples queue.', 'alt-context'),
  },
  'needs-confirmation-after-merge': {
    badge: __('Filtered: Needs confirmation after merge', 'alt-context'),
    status: __('Showing needs confirmation after merge queue only.', 'alt-context'),
    empty: __('No people in needs confirmation after merge queue.', 'alt-context'),
  },
};

const QUEUE_REVIEW_ROUTES: Partial<Record<QueueFilterId, { href: string; label: string }>> = {
  'singleton-proposals': {
    href: WORKBENCH_SCAN_ROUTE,
    label: __('Review singleton proposals in Workbench', 'alt-context'),
  },
  'hard-examples': {
    href: WORKBENCH_SCAN_ROUTE,
    label: __('Review hard examples in Workbench', 'alt-context'),
  },
  'needs-confirmation-after-merge': {
    href: WORKBENCH_SCAN_ROUTE,
    label: __('Review merge confirmations in Workbench', 'alt-context'),
  },
};

const isQueueFilterId = (value: string | null): value is QueueFilterId =>
  value !== null && Object.hasOwn(QUEUE_FILTERS, value);

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
  const queueFilter = isQueueFilterId(searchParams.get('queue')) ? searchParams.get('queue') : null;
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
  const activeFilterBadge = queueFilter !== null ? QUEUE_FILTERS[queueFilter].badge : isUnassignedFilter ? __('Filtered: Unassigned', 'alt-context') : null;
  const activeFilterStatus = queueFilter !== null ? QUEUE_FILTERS[queueFilter].status : isUnassignedFilter ? __('Showing unassigned people only.', 'alt-context') : null;
  const emptyFilterMessage = queueFilter !== null ? QUEUE_FILTERS[queueFilter].empty : isUnassignedFilter ? __('No unassigned people found.', 'alt-context') : null;
  const queueReviewRoute = queueFilter !== null ? QUEUE_REVIEW_ROUTES[queueFilter] ?? null : null;

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

  if (query.isLoading) {
    return <p>{__('Loading roster entries…', 'alt-context')}</p>;
  }

  if (query.isError) {
    return (
      <div className="acx-error-state">
        <p>{__('Unable to load roster entries.', 'alt-context')}</p>
        <button type="button" className="acx-button acx-button--secondary" onClick={() => void query.refetch()}>
          {__('Retry', 'alt-context')}
        </button>
      </div>
    );
  }

  return (
    <div className="acx-roster-section">
      <header className="acx-roster-section__header">
        <div className="acx-roster-section__title-group">
          <h2>{__('Managed Identities', 'alt-context')}</h2>
          {activeFilterBadge && <span className="acx-roster-section__filter-badge">{activeFilterBadge}</span>}
        </div>
        {!isAdding && (
          <button type="button" className="acx-button acx-button--primary" onClick={() => setIsAdding(true)}>
            <UserPlus size={16} />
            {__('Add Person', 'alt-context')}
          </button>
        )}
      </header>

      {activeFilterStatus && (
        <div className="acx-roster-section__filter" role="status">
          <p>{activeFilterStatus}</p>
          {queueReviewRoute && (
            <a href={queueReviewRoute.href} className="acx-link-button">
              {queueReviewRoute.label}
            </a>
          )}
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
              <Plus size={16} />
              {__('Create', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => setIsAdding(false)}
              disabled={createPerson.isPending}
            >
              <X size={16} />
              {__('Cancel', 'alt-context')}
            </button>
          </div>
        </form>
      )}

      {emptyFilterMessage && visibleEntries.length === 0 ? (
        <p>{emptyFilterMessage}</p>
      ) : (
        <RosterEntriesTable entries={visibleEntries} />
      )}
    </div>
  );
};

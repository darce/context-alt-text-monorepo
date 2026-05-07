import React, { useState } from 'react';
import { __ } from '@wordpress/i18n';
import { useSearchParams } from 'react-router-dom';
import type { RosterEntry } from '../../api/rosterApi';
import { RosterEntriesTable } from './RosterEntriesTable';
import { useCreatePerson } from '../../hooks/useRosterHooks';
import { UserPlus, Plus, X } from 'lucide-react';

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
  const isUnassignedFilter = personFilter === 'unassigned';
  const entries = query.data ?? [];
  const visibleEntries = isUnassignedFilter ? entries.filter((entry) => entry.cluster_count === 0) : entries;

  const clearFilter = () => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete('personFilter');
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
          {isUnassignedFilter && (
            <span className="acx-roster-section__filter-badge">{__('Filtered: Unassigned', 'alt-context')}</span>
          )}
        </div>
        {!isAdding && (
          <button type="button" className="acx-button acx-button--primary" onClick={() => setIsAdding(true)}>
            <UserPlus size={16} />
            {__('Add Person', 'alt-context')}
          </button>
        )}
      </header>

      {isUnassignedFilter && (
        <div className="acx-roster-section__filter" role="status">
          <p>{__('Showing unassigned people only.', 'alt-context')}</p>
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

      {isUnassignedFilter && visibleEntries.length === 0 ? (
        <p>{__('No unassigned people found.', 'alt-context')}</p>
      ) : (
        <RosterEntriesTable entries={visibleEntries} />
      )}
    </div>
  );
};

import React from 'react';
import { __ } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';

export interface RosterEntriesTableProps {
  entries: RosterEntry[];
}

export const RosterEntriesTable = ({ entries }: RosterEntriesTableProps): React.JSX.Element => {
  if (entries.length === 0) {
    return <p>{__('No roster entries found yet.', 'alt-context')}</p>;
  }

  return (
    <div className="acx-roster-entries">
      <table className="acx-roster-entries__table">
        <thead>
          <tr>
            <th>{__('Identity', 'alt-context')}</th>
            <th>{__('Tags', 'alt-context')}</th>
            <th>{__('Clusters', 'alt-context')}</th>
            <th>{__('Updated', 'alt-context')}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td>
                <strong>{entry.name}</strong>
              </td>
              <td>{entry.tags.length === 0 ? __('No tags', 'alt-context') : entry.tags.join(', ')}</td>
              <td>{entry.cluster_count}</td>
              <td>{new Date(entry.updated_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

import React, { useState } from 'react';
import { __ } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import { useUpdatePerson, useDeletePerson } from '../../hooks/useRosterHooks';
import { Pencil, Trash2, Check, X } from 'lucide-react';

export interface RosterEntriesTableProps {
  entries: RosterEntry[];
}

interface EditableRowProps {
  entry: RosterEntry;
}

const EditableRow = ({ entry }: EditableRowProps) => {
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(entry.name);
  const [tags, setTags] = useState(entry.tags.join(', '));

  const updatePerson = useUpdatePerson();
  const deletePerson = useDeletePerson();

  const handleSave = () => {
    updatePerson.mutate(
      {
        id: entry.id,
        name: name.trim(),
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      },
      {
        onSuccess: () => setIsEditing(false),
      }
    );
  };

  const handleCancel = () => {
    setName(entry.name);
    setTags(entry.tags.join(', '));
    setIsEditing(false);
  };

  const handleDelete = () => {
    if (window.confirm(__('Are you sure you want to delete this person? Assigned clusters will be dissociated.', 'alt-context'))) {
      deletePerson.mutate(entry.id);
    }
  };

  if (isEditing) {
    return (
      <tr>
        <td>
          <input
            type="text"
            className="acx-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={updatePerson.isPending}
            autoFocus
          />
        </td>
        <td>
          <input
            type="text"
            className="acx-input"
            value={tags}
            placeholder={__('family, friend, etc.', 'alt-context')}
            onChange={(e) => setTags(e.target.value)}
            disabled={updatePerson.isPending}
          />
        </td>
        <td>{entry.cluster_count}</td>
        <td className="acx-roster-entries__actions">
          <button
            type="button"
            className="acx-icon-button"
            onClick={handleSave}
            title={__('Save changes', 'alt-context')}
            disabled={updatePerson.isPending || !name.trim()}
          >
            <Check size={16} />
          </button>
          <button
            type="button"
            className="acx-icon-button"
            onClick={handleCancel}
            title={__('Cancel', 'alt-context')}
            disabled={updatePerson.isPending}
          >
            <X size={16} />
          </button>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td>
        <strong>{entry.name}</strong>
      </td>
      <td>{entry.tags.length === 0 ? __('No tags', 'alt-context') : entry.tags.join(', ')}</td>
      <td>{entry.cluster_count}</td>
      <td className="acx-roster-entries__actions">
        <button
          type="button"
          className="acx-icon-button"
          onClick={() => setIsEditing(true)}
          title={__('Edit person', 'alt-context')}
        >
          <Pencil size={16} />
        </button>
        <button
          type="button"
          className="acx-icon-button acx-icon-button--danger"
          onClick={handleDelete}
          title={__('Delete person', 'alt-context')}
          disabled={deletePerson.isPending}
        >
          <Trash2 size={16} />
        </button>
      </td>
    </tr>
  );
};

export const RosterEntriesTable = ({ entries }: RosterEntriesTableProps): React.JSX.Element => {
  if (entries.length === 0) {
    return <p>{__('No people yet. Add one manually or assign a cluster.', 'alt-context')}</p>;
  }

  return (
    <div className="acx-roster-entries">
      <table className="acx-roster-entries__table">
        <thead>
          <tr>
            <th>{__('Identity', 'alt-context')}</th>
            <th>{__('Tags', 'alt-context')}</th>
            <th>{__('Clusters', 'alt-context')}</th>
            <th>{__('Actions', 'alt-context')}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <EditableRow key={entry.id} entry={entry} />
          ))}
        </tbody>
      </table>
    </div>
  );
};

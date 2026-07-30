import React, { useState } from 'react';
import { __ } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import { useUpdatePerson, useDeletePerson } from '../../hooks/useRosterHooks';
import { AlertCircle, Check, CheckCircle2, Pencil, Trash2, UserRound, X } from 'lucide-react';
import { ConfirmDialog } from './ConfirmDialog';
import { derivePersonState, PERSON_STATES, type PersonState } from './personState';

export interface RosterEntriesTableProps {
  entries: RosterEntry[];
}

interface EditableRowProps {
  entry: RosterEntry;
}

const STATE_PRESENTATION: Record<
  PersonState,
  {
    label: string;
    Icon: typeof AlertCircle;
    className: string;
  }
> = {
  [PERSON_STATES.NEEDS_REVIEW]: {
    label: __('Needs review', 'alt-context'),
    Icon: AlertCircle,
    className: 'acx-roster-entries__state--needs-review',
  },
  [PERSON_STATES.UNNAMED]: {
    label: __('Unnamed', 'alt-context'),
    Icon: UserRound,
    className: 'acx-roster-entries__state--unnamed',
  },
  [PERSON_STATES.NAMED]: {
    label: __('Named', 'alt-context'),
    Icon: CheckCircle2,
    className: 'acx-roster-entries__state--named',
  },
};

const PersonStateCell = ({ entry }: { entry: RosterEntry }): React.JSX.Element => {
  const state = derivePersonState(entry);
  const { label, Icon, className } = STATE_PRESENTATION[state];

  return (
    <td>
      <span className={`acx-roster-entries__state ${className}`}>
        <Icon size={16} aria-hidden="true" />
        <span className="acx-roster-entries__state-label">{label}</span>
      </span>
    </td>
  );
};

const EditableRow = ({ entry }: EditableRowProps) => {
  const [isEditing, setIsEditing] = useState(false);
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
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
      },
    );
  };

  const handleCancel = () => {
    setName(entry.name);
    setTags(entry.tags.join(', '));
    setIsEditing(false);
  };

  const handleDelete = () => {
    deletePerson.mutate(entry.id, {
      onSuccess: () => setIsDeleteConfirmOpen(false),
    });
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
        <PersonStateCell entry={entry} />
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
    <>
      <tr>
        <td>
          <strong>{entry.name}</strong>
        </td>
        <PersonStateCell entry={entry} />
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
            onClick={() => setIsDeleteConfirmOpen(true)}
            title={__('Delete person', 'alt-context')}
            disabled={deletePerson.isPending}
          >
            <Trash2 size={16} />
          </button>
        </td>
      </tr>
      <ConfirmDialog
        open={isDeleteConfirmOpen}
        onOpenChange={setIsDeleteConfirmOpen}
        onConfirm={handleDelete}
        onCancel={() => setIsDeleteConfirmOpen(false)}
        title={__('Delete person', 'alt-context')}
        description={__(
          'Are you sure you want to delete this person? Assigned clusters will be dissociated.',
          'alt-context',
        )}
        confirmLabel={__('Delete', 'alt-context')}
        isPending={deletePerson.isPending}
      />
    </>
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
            <th>{__('State', 'alt-context')}</th>
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

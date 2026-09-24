import React, { useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import type { RosterEntryInstance } from '../../api/generated/roster-entry';
import { useUpdatePerson, useDeletePerson } from '../../hooks/useRosterHooks';
import { AlertCircle, Check, CheckCircle2, Pencil, Merge, Trash2, UserRound, X } from 'lucide-react';
import { ConfirmDialog } from '../../components/ui/ConfirmDialog';
import { IdentityThumbnail } from './IdentityThumbnail';
import { derivePersonState, PERSON_STATES, type PersonState } from './personState';
import { isHumanLabeledTarget } from '../workbench/identity-clusters/suggestionProjection';
import { getEntryPersonUuid } from './rosterRoute';

const RESERVED_LABEL_MESSAGE = __(
  'This name format is reserved for automatic face group IDs. Choose a descriptive name.',
  'alt-context',
);

export interface RosterEntriesTableProps {
  entries: RosterEntry[];
  onOpenPerson?: (entry: RosterEntry) => void;
  onMergePerson?: (entry: RosterEntry) => void;
}

interface EditableRowProps {
  entry: RosterEntry;
  onOpenPerson?: (entry: RosterEntry) => void;
  onMergePerson?: (entry: RosterEntry) => void;
}

/** Dense table-row size — not the drawer default (96/128). */
const DIRECTORY_THUMB_SIZE = 32;

/**
 * Pick the representative face for a directory row.
 *
 * Rule: the cluster with the highest `identity_count` (most-confirmed face for
 * that person). Ties broken by `cluster_id` ascending so the choice is stable
 * across renders for the same entry.
 */
export const selectRepresentativeIdentity = (entry: RosterEntry): RosterEntryInstance | null => {
  const clusters = entry.clusters;
  if (!clusters || clusters.length === 0) {
    return null;
  }

  let best = clusters[0];
  for (let i = 1; i < clusters.length; i++) {
    const candidate = clusters[i];
    if (
      candidate.identity_count > best.identity_count ||
      (candidate.identity_count === best.identity_count && candidate.cluster_id < best.cluster_id)
    ) {
      best = candidate;
    }
  }

  return best.representative_identity;
};

const DirectoryFace = ({ entry }: { entry: RosterEntry }): React.JSX.Element => {
  const rep = selectRepresentativeIdentity(entry);

  // Decorative empty alt only when a non-blank name label sits beside the face
  // [A11Y-21]. Unnamed rows have no adjacent text equivalent — omit alt so
  // IdentityThumbnail's default ("Face from media %d") names the face [S6-BR-03].
  const decorativeAlt = entry.name.trim() !== '' ? '' : undefined;

  // Empty cases: no clusters / null representative / null media_url → placeholder.
  // IdentityThumbnail renders the sized placeholder when it has no resolvable src.
  // Explicit null guards keep those paths intentional [PERC-02].
  if (rep === null) {
    return (
      <IdentityThumbnail identity={{ media_id: 0 }} size={DIRECTORY_THUMB_SIZE} alt={decorativeAlt} />
    );
  }
  if (rep.media_url === null) {
    return (
      <IdentityThumbnail
        identity={{ media_id: rep.media_id, identity_id: rep.identity_id }}
        size={DIRECTORY_THUMB_SIZE}
        alt={decorativeAlt}
      />
    );
  }

  // Pass only fields ThumbnailIdentity reads — never a fabricated ClusterIdentity.
  // Object-form pixel bbox (contract parity) enables canvas crop of the face.
  return (
    <IdentityThumbnail
      identity={{
        media_id: rep.media_id,
        identity_id: rep.identity_id,
        media_url: rep.media_url,
        bbox: rep.bbox,
      }}
      size={DIRECTORY_THUMB_SIZE}
      alt={decorativeAlt}
    />
  );
};

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

const EditableRow = ({ entry, onOpenPerson, onMergePerson }: EditableRowProps) => {
  const displayName = entry.name.trim() || __('Unnamed person', 'alt-context');
  const [isEditing, setIsEditing] = useState(false);
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [name, setName] = useState(entry.name);
  const [tags, setTags] = useState(entry.tags.join(', '));
  const [nameError, setNameError] = useState<string | null>(null);

  const updatePerson = useUpdatePerson();
  const deletePerson = useDeletePerson();
  const canOpenPerson = getEntryPersonUuid(entry) !== null;

  const handleSave = () => {
    const trimmedName = name.trim();
    // BR-60/BR-63: reject reserved machine-shaped names on rename only;
    // allow tag-only saves when the existing (possibly legacy) name is unchanged.
    const nameUnchanged = trimmedName === entry.name.trim();
    if (!nameUnchanged && !isHumanLabeledTarget(trimmedName)) {
      setNameError(RESERVED_LABEL_MESSAGE);
      return;
    }
    setNameError(null);
    updatePerson.mutate(
      {
        id: entry.id,
        name: trimmedName,
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
    setNameError(null);
    setIsEditing(false);
  };

  const handleEditKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (!updatePerson.isPending && name.trim()) {
        handleSave();
      }
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      handleCancel();
    }
  };

  const handleDelete = () => {
    deletePerson.mutate(entry.id, {
      onSuccess: () => setIsDeleteConfirmOpen(false),
    });
  };

  if (isEditing) {
    const nameErrorId = `acx-roster-edit-name-error-${entry.id}`;
    const nameInputId = `acx-roster-edit-name-${entry.id}`;
    const tagsInputId = `acx-roster-edit-tags-${entry.id}`;
    return (
      <tr>
        <td>
          <label className="acx-roster-field-label" htmlFor={nameInputId}>
            {__('Person name', 'alt-context')}
          </label>
          <DirectoryFace entry={entry} />{' '}
          <input
            id={nameInputId}
            type="text"
            className="acx-input"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (nameError) {
                setNameError(null);
              }
            }}
            onKeyDown={handleEditKeyDown}
            disabled={updatePerson.isPending}
            autoFocus
            aria-invalid={nameError ? true : undefined}
            aria-describedby={nameError ? nameErrorId : undefined}
          />
          {nameError && (
            <p id={nameErrorId} className="acx-roster-entries__name-error" role="alert">
              {nameError}
            </p>
          )}
        </td>
        <PersonStateCell entry={entry} />
        <td>
          <label className="acx-roster-field-label" htmlFor={tagsInputId}>
            {__('Tags', 'alt-context')}
          </label>
          <input
            id={tagsInputId}
            type="text"
            className="acx-input"
            value={tags}
            placeholder={__('family, friend, etc.', 'alt-context')}
            onChange={(e) => setTags(e.target.value)}
            onKeyDown={handleEditKeyDown}
            disabled={updatePerson.isPending}
          />
        </td>
        <td>{entry.cluster_count}</td>
        <td className="acx-roster-entries__actions">
          <button
            type="button"
            className="acx-icon-button"
            onClick={handleSave}
            aria-label={sprintf(__('Save changes to %s', 'alt-context'), displayName)}
            title={__('Save changes', 'alt-context')}
            disabled={updatePerson.isPending || !name.trim()}
          >
            <Check size={16} />
          </button>
          <button
            type="button"
            className="acx-icon-button"
            onClick={handleCancel}
            aria-label={sprintf(__('Cancel editing %s', 'alt-context'), displayName)}
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
          {canOpenPerson ? (
            <button
              type="button"
              className="acx-roster-entries__open"
              aria-label={displayName}
              onClick={() => onOpenPerson?.(entry)}
            >
              <DirectoryFace entry={entry} />
              <strong>{displayName}</strong>
            </button>
          ) : (
            <span className="acx-roster-entries__open acx-roster-entries__open--static">
              <DirectoryFace entry={entry} />
              <strong>{displayName}</strong>
            </span>
          )}
        </td>
        <PersonStateCell entry={entry} />
        <td>{entry.tags.length === 0 ? __('No tags', 'alt-context') : entry.tags.join(', ')}</td>
        <td>
          {canOpenPerson ? (
            <button
              type="button"
              className="acx-roster-entries__open"
              aria-label={sprintf(
                /* translators: 1: face group count, 2: person name */
                __('Open %1$d face groups for %2$s', 'alt-context'),
                entry.cluster_count,
                displayName,
              )}
              onClick={() => onOpenPerson?.(entry)}
            >
              {entry.cluster_count}
            </button>
          ) : (
            <span
              className="acx-roster-entries__open acx-roster-entries__open--static"
              title={__('Person workspace unavailable for this entry yet.', 'alt-context')}
            >
              {entry.cluster_count}
            </span>
          )}
        </td>
        <td className="acx-roster-entries__actions">
          <button
            type="button"
            className="acx-icon-button"
            onClick={() => setIsEditing(true)}
            title={__('Edit person', 'alt-context')}
          >
            <Pencil size={16} />
          </button>
          <button type="button" className="acx-icon-button" title={__('Merge into…', 'alt-context')}
            aria-label={sprintf(__('Merge %s into another person', 'alt-context'), displayName)}
            onClick={() => onMergePerson?.(entry)}>
            <Merge size={16} aria-hidden="true" />
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
          'Are you sure you want to delete this person? Assigned faces return to the review queue.',
          'alt-context',
        )}
        confirmLabel={__('Delete', 'alt-context')}
        isPending={deletePerson.isPending}
      />
    </>
  );
};

export const RosterEntriesTable = ({ entries, onOpenPerson, onMergePerson }: RosterEntriesTableProps): React.JSX.Element => {
  if (entries.length === 0) {
    return <p>{__('No people yet. Add one manually or assign a face group.', 'alt-context')}</p>;
  }

  return (
    <div className="acx-roster-entries">
      <table className="acx-roster-entries__table">
        <thead>
          <tr>
            <th>{__('Person', 'alt-context')}</th>
            <th>{__('State', 'alt-context')}</th>
            <th>{__('Tags', 'alt-context')}</th>
            <th>{__('Face groups', 'alt-context')}</th>
            <th>{__('Actions', 'alt-context')}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <EditableRow key={entry.id} entry={entry} onOpenPerson={onOpenPerson} onMergePerson={onMergePerson} />
          ))}
        </tbody>
      </table>
    </div>
  );
};

import React, { useState } from 'react';
import { __ } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import type { RosterEntryInstance } from '../../api/generated/roster-entry';
import { useUpdatePerson, useDeletePerson } from '../../hooks/useRosterHooks';
import { AlertCircle, Check, CheckCircle2, Pencil, Trash2, UserRound, X } from 'lucide-react';
import { ConfirmDialog } from './ConfirmDialog';
import { IdentityThumbnail } from './IdentityThumbnail';
import { derivePersonState, PERSON_STATES, type PersonState } from './personState';
import { isHumanLabeledTarget } from '../workbench/identity-clusters/suggestionProjection';

const RESERVED_LABEL_MESSAGE = __(
  'This name format is reserved for automatic face group IDs. Choose a descriptive name.',
  'alt-context',
);

export interface RosterEntriesTableProps {
  entries: RosterEntry[];
}

interface EditableRowProps {
  entry: RosterEntry;
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
  // IdentityThumbnail's default ("Identity from media %d") names the face [S6-BR-03].
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

const EditableRow = ({ entry }: EditableRowProps) => {
  const [isEditing, setIsEditing] = useState(false);
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [name, setName] = useState(entry.name);
  const [tags, setTags] = useState(entry.tags.join(', '));
  const [nameError, setNameError] = useState<string | null>(null);

  const updatePerson = useUpdatePerson();
  const deletePerson = useDeletePerson();

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

  const handleDelete = () => {
    deletePerson.mutate(entry.id, {
      onSuccess: () => setIsDeleteConfirmOpen(false),
    });
  };

  if (isEditing) {
    const nameErrorId = `acx-roster-edit-name-error-${entry.id}`;
    return (
      <tr>
        <td>
          <DirectoryFace entry={entry} />{' '}
          <input
            type="text"
            className="acx-input"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (nameError) {
                setNameError(null);
              }
            }}
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
          <DirectoryFace entry={entry} />{' '}
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
          'Are you sure you want to delete this person? Assigned faces return to the review queue.',
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
            <EditableRow key={entry.id} entry={entry} />
          ))}
        </tbody>
      </table>
    </div>
  );
};

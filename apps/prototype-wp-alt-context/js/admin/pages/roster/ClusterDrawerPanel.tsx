import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import type { ClusterIdentity, ClusterSummary } from '../../api/recognition';
import type { RosterEntry } from '../../api/rosterApi';
import type { MediaMap } from './hooks/useClusterMediaMap';
import { mediaEditUrl } from '../../utils/adminUrls';
import { IdentityThumbnail } from './IdentityThumbnail';
import { Combobox } from '../../../components/ui/combobox';

interface Props {
  cluster: ClusterSummary | null;
  identities: ClusterIdentity[];
  mediaMap: MediaMap;
  onClose: () => void;
  onRescanCluster: (cluster: ClusterSummary, identities: ClusterIdentity[]) => void;
  isRescanning: boolean;
  onCommitCluster: (cluster: ClusterSummary, assignment: { rosterEntryId?: number; newEntryName?: string }) => void;
  isCommitting: boolean;
  rosterEntries: RosterEntry[];
  statusMessage?: string | null;
  errorMessage?: string | null;
  isDetailLoading: boolean;
  detailError?: string | null;
  onFaceDragStart: (clusterId: string, faceId: string) => void;
  onFaceDragEnd: () => void;
  onDropTargetChange: (target: string | null) => void;
  dropTarget: string | null;
  isDragging: boolean;
  onDiscardDrop: () => void;
}

export const ClusterDrawerPanel = ({
  cluster,
  identities,
  mediaMap,
  onClose,
  onRescanCluster,
  isRescanning,
  onCommitCluster,
  isCommitting,
  rosterEntries,
  statusMessage,
  errorMessage,
  isDetailLoading,
  detailError,
  onFaceDragStart,
  onFaceDragEnd,
  onDropTargetChange,
  dropTarget,
  isDragging,
  onDiscardDrop,
}: Props): React.JSX.Element | null => {
  const [selectedEntryId, setSelectedEntryId] = React.useState('');
  const [newEntryName, setNewEntryName] = React.useState('');

  const createFaceDragStart = React.useCallback(
    (faceId: string) => (event: React.DragEvent<HTMLElement>) => {
      if (!cluster) {
        return;
      }
      event.dataTransfer?.setData('text/plain', faceId);
      event.dataTransfer?.setDragImage(event.currentTarget, 0, 0);
      onFaceDragStart(cluster.id, faceId);
    },
    [onFaceDragStart, cluster],
  );

  const handleDropzoneDragOver = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (!isDragging) {
        return;
      }
      event.preventDefault();
      onDropTargetChange('discard');
    },
    [isDragging, onDropTargetChange],
  );

  const handleDropzoneDrop = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      if (!isDragging) {
        return;
      }
      event.preventDefault();
      onDropTargetChange(null);
      onDiscardDrop();
    },
    [isDragging, onDiscardDrop, onDropTargetChange],
  );

  React.useEffect(() => {
    setSelectedEntryId('');
    setNewEntryName('');
  }, [cluster?.id]);

  if (!cluster) {
    return null;
  }

  const isCreatingEntry = selectedEntryId === 'create';
  const canCommit = (isCreatingEntry && newEntryName.trim().length > 0) || (!isCreatingEntry && selectedEntryId !== '');
  const identitiesToDisplay = identities ?? [];
  const hasIdentities = identitiesToDisplay.length > 0;

  const handleCommit = () => {
    if (!canCommit) {
      return;
    }

    const assignment = isCreatingEntry
      ? { newEntryName: newEntryName.trim() }
      : { rosterEntryId: Number.parseInt(selectedEntryId, 10) };

    onCommitCluster(cluster, assignment);
  };

  return (
    <>
      <div className="acx-cluster-drawer__backdrop" onClick={onClose} />
      <aside className="acx-cluster-drawer" aria-live="polite">
        <header className="acx-cluster-drawer__header">
          <div>
            <p className="acx-cluster-drawer__label">{__('Cluster', 'alt-context')}</p>
            <h3>{cluster.label || cluster.id}</h3>
            <p>
              {sprintf(
                _n('%d identity', '%d identities', cluster.identity_count, 'alt-context'),
                cluster.identity_count,
              )}
            </p>
          </div>
          <button type="button" className="acx-link-button" onClick={onClose}>
            {__('Close', 'alt-context')}
          </button>
        </header>

        <div className="acx-cluster-drawer__faces">
          {isDetailLoading ? (
            <p>{__('Loading identities…', 'alt-context')}</p>
          ) : !hasIdentities ? (
            <p>{__('No identities found for this cluster.', 'alt-context')}</p>
          ) : (
            identitiesToDisplay.map((identity) => (
              <figure
                key={identity.identity_id}
                className="acx-cluster-drawer__face"
                draggable
                aria-label={sprintf(__('Move identity from media %d', 'alt-context'), identity.media_id)}
                onDragStart={createFaceDragStart(identity.identity_id)}
                onDragEnd={onFaceDragEnd}
              >
                <a href={mediaEditUrl(identity.media_id)} target="_blank" rel="noopener noreferrer">
                  <IdentityThumbnail identity={identity} mediaMeta={mediaMap[identity.media_id]} size={128} />
                </a>
                <figcaption>
                  {sprintf(__('Similarity: %s', 'alt-context'), identity.similarity.toFixed(2))}
                  <br />
                  {sprintf(__('Media %d', 'alt-context'), identity.media_id)}
                </figcaption>
              </figure>
            ))
          )}
        </div>

        {detailError && <p className="acx-cluster-drawer__status acx-cluster-drawer__status--error">{detailError}</p>}

        <div className="acx-cluster-drawer__dropzone-wrapper">
          <div
            className={`acx-cluster-drawer__dropzone${dropTarget === 'discard' ? ' is-drop-target' : ''}`}
            onDragOver={handleDropzoneDragOver}
            onDragLeave={() => {
              if (dropTarget === 'discard') {
                onDropTargetChange(null);
              }
            }}
            onDrop={handleDropzoneDrop}
          >
            {__('Drop identities here to remove them from this cluster.', 'alt-context')}
          </div>
        </div>

        <div className="acx-cluster-drawer__actions">
          <button
            type="button"
            className="acx-apply-panel__scan"
            onClick={() => onRescanCluster(cluster, identitiesToDisplay)}
            disabled={isRescanning || !hasIdentities}
          >
            {isRescanning ? __('Rescanning…', 'alt-context') : __('Rescan with sensitive settings', 'alt-context')}
          </button>
        </div>

        <div className="acx-cluster-drawer__assignment">
          <label htmlFor="acx-roster-entry-select">{__('Commit to roster entry', 'alt-context')}</label>
          <Combobox
            options={[
              { value: '', label: __('Select an entry', 'alt-context') },
              ...rosterEntries.map((entry) => ({
                value: entry.id.toString(),
                label: entry.name,
              })),
              { value: 'create', label: __('Create new entry…', 'alt-context') },
            ]}
            value={selectedEntryId}
            onSelect={(nextValue: string) => setSelectedEntryId(nextValue)}
            ariaLabel={__('Commit to roster entry', 'alt-context')}
            placeholder={__('Select an entry', 'alt-context')}
            className="acx-cluster-drawer__select"
            id="acx-roster-entry-select"
          />

          {selectedEntryId === 'create' && (
            <input
              type="text"
              className="acx-cluster-drawer__input"
              value={newEntryName}
              onChange={(event) => setNewEntryName(event.target.value)}
              placeholder={__('New roster entry name', 'alt-context')}
            />
          )}

          <button
            type="button"
            className="acx-link-button"
            onClick={handleCommit}
            disabled={!canCommit || isCommitting}
          >
            {isCommitting ? __('Committing…', 'alt-context') : __('Commit to roster entry', 'alt-context')}
          </button>
        </div>

        {statusMessage && <p className="acx-cluster-drawer__status">{statusMessage}</p>}
        {errorMessage && <p className="acx-cluster-drawer__status acx-cluster-drawer__status--error">{errorMessage}</p>}
      </aside>
    </>
  );
};

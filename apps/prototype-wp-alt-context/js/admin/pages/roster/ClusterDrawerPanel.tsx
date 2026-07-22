import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import type { ClusterIdentity, ClusterSummary } from '../../api/recognition';
import type { RosterEntry } from '../../api/rosterApi';
import type { MediaMap } from './hooks/useClusterMediaMap';
import { mediaEditUrl } from '../../utils/adminUrls';
import { IdentityThumbnail } from './IdentityThumbnail';
import { Combobox } from '../../../components/ui/combobox';
import { Check, X } from 'lucide-react';
import { useFocusTrap } from './hooks/useFocusTrap';

export interface ClusterReassignTarget {
  id: string;
  label: string;
}

interface Props {
  cluster: ClusterSummary | null;
  identities: ClusterIdentity[];
  mediaMap: MediaMap;
  onClose: () => void;
  onRescanCluster: (cluster: ClusterSummary, identities: ClusterIdentity[]) => void;
  isRescanning: boolean;
  /** Remote-compute offline gate for sensitive rescan (RES-15). */
  rescanDisabled?: boolean;
  rescanTitle?: string;
  rescanAriaDisabled?: true;
  onCommitCluster: (cluster: ClusterSummary, assignment: { rosterEntryId?: number; newEntryName?: string }) => void;
  onOpenPersonWorkspace: (personUuid: string) => void;
  isCommitting: boolean;
  rosterEntries: RosterEntry[];
  isDetailLoading: boolean;
  detailError?: string | null;

  onFaceDragStart: (clusterId: string, faceId: string) => void;
  onFaceDragEnd: () => void;
  onDropTargetChange: (target: string | null) => void;
  dropTarget: string | null;
  isDragging: boolean;
  onDiscardDrop: () => void;

  /** Other clusters available as reassignment targets (current cluster already excluded). */
  reassignTargets?: ClusterReassignTarget[];
  /** Single atomic reassign call (rg-002); same mutation as drag path. */
  onReassignFace?: (faceId: string, targetClusterId: string) => void;
  isReassigning?: boolean;
  reassignErrorMessage?: string | null;
}

const EMPTY_TARGETS: ClusterReassignTarget[] = [];
const NO_TARGETS_REASON = __('No other clusters available to move this identity into.', 'alt-context');
const NO_TARGETS_REASON_ID = 'acx-cluster-drawer-no-move-targets-reason';

const clusterTargetLabel = (target: ClusterReassignTarget): string =>
  target.label.trim().length > 0
    ? target.label
    : sprintf(__('Cluster %s', 'alt-context'), target.id.slice(0, 8));

export const ClusterDrawerPanel = ({
  cluster,
  identities,
  mediaMap,
  onClose,
  onRescanCluster,
  isRescanning,
  rescanDisabled = false,
  rescanTitle,
  rescanAriaDisabled,
  onCommitCluster,
  onOpenPersonWorkspace,
  isCommitting,
  rosterEntries,
  isDetailLoading,
  detailError,

  onFaceDragStart,
  onFaceDragEnd,
  onDropTargetChange,
  dropTarget,
  isDragging,
  onDiscardDrop,

  reassignTargets = EMPTY_TARGETS,
  onReassignFace,
  isReassigning = false,
  reassignErrorMessage = null,
}: Props): React.JSX.Element | null => {
  const [selectedEntryId, setSelectedEntryId] = React.useState('');
  const [newEntryName, setNewEntryName] = React.useState('');
  const [pickerFaceId, setPickerFaceId] = React.useState<string | null>(null);
  const [statusMessage, setStatusMessage] = React.useState('');
  const closeButtonRef = React.useRef<HTMLButtonElement>(null);
  const drawerRef = React.useRef<HTMLElement>(null);
  const pickerFirstOptionRef = React.useRef<HTMLButtonElement>(null);
  const moveOpenerRef = React.useRef<HTMLButtonElement | null>(null);
  const restoreMoveFocusRef = React.useRef(false);
  const pendingReassignRef = React.useRef<{ faceId: string; targetLabel: string } | null>(null);

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
    setPickerFaceId(null);
    setStatusMessage('');
    pendingReassignRef.current = null;
    restoreMoveFocusRef.current = false;
    moveOpenerRef.current = null;
  }, [cluster?.id]);

  const closePicker = React.useCallback((restoreFocus = true) => {
    if (restoreFocus) {
      restoreMoveFocusRef.current = true;
    }
    setPickerFaceId(null);
  }, []);

  React.useEffect(() => {
    if (pickerFaceId === null) {
      if (restoreMoveFocusRef.current) {
        restoreMoveFocusRef.current = false;
        moveOpenerRef.current?.focus();
      }
      return;
    }
    if (reassignTargets.length === 0) {
      restoreMoveFocusRef.current = true;
      setPickerFaceId(null);
      return;
    }
    pickerFirstOptionRef.current?.focus();
  }, [pickerFaceId, reassignTargets.length]);

  React.useEffect(() => {
    const pending = pendingReassignRef.current;
    if (!pending || isReassigning) {
      return;
    }
    if (reassignErrorMessage) {
      setStatusMessage(reassignErrorMessage);
    } else {
      setStatusMessage(
        sprintf(__('Moved identity to %s.', 'alt-context'), pending.targetLabel),
      );
    }
    pendingReassignRef.current = null;
  }, [isReassigning, reassignErrorMessage]);

  const handleCreate = (name: string) => {
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }

    setSelectedEntryId('create');
    setNewEntryName(trimmed);
  };

  const handleSelectEntry = (nextValue: string) => {
    setSelectedEntryId(nextValue);
    if (nextValue !== 'create') {
      setNewEntryName('');
    }
  };

  const handleDrawerKeyDown = useFocusTrap({
    rootRef: drawerRef,
    initialFocusRef: closeButtonRef,
    onEscape: onClose,
    activeKey: cluster?.id ?? null,
  });

  const handlePickerKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        closePicker(true);
      }
    },
    [closePicker],
  );

  const handleOpenPicker = React.useCallback(
    (faceId: string, opener: HTMLButtonElement) => {
      if (reassignTargets.length === 0 || !onReassignFace) {
        return;
      }
      moveOpenerRef.current = opener;
      setPickerFaceId((current) => {
        if (current === faceId) {
          restoreMoveFocusRef.current = true;
          return null;
        }
        restoreMoveFocusRef.current = false;
        return faceId;
      });
    },
    [onReassignFace, reassignTargets.length],
  );

  const handleSelectTarget = React.useCallback(
    (faceId: string, target: ClusterReassignTarget) => {
      if (!onReassignFace) {
        return;
      }
      const targetLabel = clusterTargetLabel(target);
      pendingReassignRef.current = { faceId, targetLabel };
      setStatusMessage(sprintf(__('Moving identity to %s…', 'alt-context'), targetLabel));
      closePicker(true);
      onReassignFace(faceId, target.id);
    },
    [closePicker, onReassignFace],
  );

  const selectedEntry = React.useMemo(
    () => rosterEntries.find((entry) => entry.id.toString() === selectedEntryId) ?? null,
    [rosterEntries, selectedEntryId],
  );

  if (!cluster) {
    return null;
  }

  const isCreatingEntry = selectedEntryId === 'create';
  const canCommit = (isCreatingEntry && newEntryName.trim().length > 0) || (!isCreatingEntry && selectedEntryId !== '');
  const selectedPersonUuid = selectedEntry?.person_uuid ?? null;
  const identitiesToDisplay = identities ?? [];
  const hasIdentities = identitiesToDisplay.length > 0;
  const hasReassignTargets = reassignTargets.length > 0;
  // Native disabled only for busy/missing handler — empty targets stay focusable (aria-disabled).
  const moveNativelyDisabled = isReassigning || !onReassignFace;
  const moveAriaDisabled = !hasReassignTargets || moveNativelyDisabled;

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
      <aside className="acx-cluster-drawer" aria-live="polite" ref={drawerRef} onKeyDown={handleDrawerKeyDown}>
        <header className="acx-cluster-drawer__header">
          <div className="acx-cluster-drawer__title-group">
            <span className="acx-cluster-drawer__eyebrow">{__('Cluster Identity', 'alt-context')}</span>
            <h3 className="acx-cluster-drawer__title">
              {cluster.label || sprintf(__('Cluster %s', 'alt-context'), cluster.id.slice(0, 8))}
            </h3>
            <ul className="acx-cluster-drawer__meta">
              <li>
                <strong>{__('Faces:', 'alt-context')}</strong>
                {sprintf(
                  _n('%d identity', '%d identities', cluster.identity_count, 'alt-context'),
                  cluster.identity_count,
                )}
              </li>
              {cluster.confidence_score !== undefined && (
                <li>
                  <strong>{__('Confidence:', 'alt-context')}</strong>
                  {sprintf('%d%%', Math.round(cluster.confidence_score * 100))}
                </li>
              )}
              {cluster.created_at && (
                <li>
                  <strong>{__('Found:', 'alt-context')}</strong>
                  {new Date(cluster.created_at).toLocaleDateString()}
                </li>
              )}
            </ul>
          </div>
          <button
            type="button"
            className="acx-icon-button"
            onClick={onClose}
            title={__('Close', 'alt-context')}
            ref={closeButtonRef}
          >
            <X size={20} />
          </button>
        </header>

        <div className="acx-cluster-drawer__faces">
          {isDetailLoading ? (
            <p>{__('Loading identities…', 'alt-context')}</p>
          ) : !hasIdentities ? (
            <p>{__('No identities found for this cluster.', 'alt-context')}</p>
          ) : (
            <>
              {!hasReassignTargets ? (
                <span id={NO_TARGETS_REASON_ID} className="screen-reader-text">
                  {NO_TARGETS_REASON}
                </span>
              ) : null}
              {identitiesToDisplay.map((identity) => {
                const pickerOpen = pickerFaceId === identity.identity_id;
                const moveButtonLabel = sprintf(
                  __('Move to… identity from media %d', 'alt-context'),
                  identity.media_id,
                );
                return (
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
                      {sprintf(
                        __('Similarity: %s', 'alt-context'),
                        identity.similarity === null ? __('Unknown', 'alt-context') : identity.similarity.toFixed(2),
                      )}
                      <br />
                      {sprintf(__('Media %d', 'alt-context'), identity.media_id)}
                    </figcaption>
                    <div className="acx-cluster-drawer__face-actions">
                      <button
                        type="button"
                        className="acx-cluster-drawer__move-btn"
                        aria-label={moveButtonLabel}
                        aria-haspopup="menu"
                        aria-expanded={pickerOpen}
                        aria-controls={
                          pickerOpen ? `acx-cluster-move-targets-${identity.identity_id}` : undefined
                        }
                        disabled={moveNativelyDisabled}
                        aria-disabled={moveAriaDisabled ? true : undefined}
                        aria-describedby={!hasReassignTargets ? NO_TARGETS_REASON_ID : undefined}
                        onClick={(event) => handleOpenPicker(identity.identity_id, event.currentTarget)}
                      >
                        {__('Move to…', 'alt-context')}
                      </button>
                      {pickerOpen ? (
                        <div
                          id={`acx-cluster-move-targets-${identity.identity_id}`}
                          className="acx-cluster-drawer__move-picker"
                          role="menu"
                          aria-label={__('Choose a target cluster', 'alt-context')}
                          onKeyDown={handlePickerKeyDown}
                        >
                          {reassignTargets.map((target, index) => {
                            const label = clusterTargetLabel(target);
                            return (
                              <button
                                key={target.id}
                                type="button"
                                role="menuitem"
                                className="acx-cluster-drawer__move-option"
                                ref={index === 0 ? pickerFirstOptionRef : undefined}
                                onClick={() => handleSelectTarget(identity.identity_id, target)}
                              >
                                {label}
                              </button>
                            );
                          })}
                          <button
                            type="button"
                            role="menuitem"
                            className="acx-cluster-drawer__move-cancel"
                            onClick={() => closePicker(true)}
                          >
                            {__('Cancel', 'alt-context')}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </figure>
                );
              })}
            </>
          )}
        </div>

        <p
          className="acx-cluster-drawer__reassign-status"
          role="status"
          aria-live="polite"
          data-testid="cluster-drawer-reassign-status"
        >
          {statusMessage}
        </p>

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
            disabled={isRescanning || !hasIdentities || rescanDisabled}
            aria-disabled={rescanAriaDisabled}
            title={rescanTitle}
          >
            {isRescanning ? __('Rescanning…', 'alt-context') : __('Rescan with sensitive settings', 'alt-context')}
          </button>
        </div>

        <div className="acx-cluster-drawer__assignment">
          <label className="acx-cluster-drawer__section-label" htmlFor="acx-roster-entry-select">
            {__('Assign to Identity', 'alt-context')}
          </label>
          <div className="acx-cluster-drawer__assignment-controls">
            <Combobox
              options={[
                ...rosterEntries.map((entry) => ({
                  value: entry.id.toString(),
                  label: entry.name,
                })),
              ]}
              value={selectedEntryId}
              onSelect={handleSelectEntry}
              onCreate={handleCreate}
              ariaLabel={__('Commit to roster entry', 'alt-context')}
              placeholder={__('Assign to…', 'alt-context')}
              className="acx-cluster-drawer__select"
              id="acx-roster-entry-select"
              portalContainer={drawerRef.current}
            />

            <button
              type="button"
              className="acx-button acx-button--primary acx-cluster-drawer__commit-btn"
              onClick={handleCommit}
              disabled={!canCommit || isCommitting}
            >
              {isCommitting ? (
                <>
                  <span className="acx-spinner" aria-hidden="true" />
                  {__('Committing…', 'alt-context')}
                </>
              ) : (
                <>
                  <Check size={16} />
                  {__('Confirm Assignment', 'alt-context')}
                </>
              )}
            </button>
            <button
              type="button"
              className="acx-button acx-cluster-drawer__workspace-btn"
              onClick={() => {
                if (selectedPersonUuid) {
                  onOpenPersonWorkspace(selectedPersonUuid);
                }
              }}
              disabled={!selectedPersonUuid}
            >
              {__('Open person workspace', 'alt-context')}
            </button>
          </div>
        </div>
      </aside>
    </>
  );
};

import React, { useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ConflictRecord, ConflictResolutionChoice } from '../../api/recognition';
import { useConflictDetail } from '../../hooks/useConflictDetail';
import { useConflicts } from '../../hooks/useConflicts';
import { useResolveConflict } from '../../hooks/useResolveConflict';
import { useSyncTrigger } from '../../hooks/useSyncTrigger';

const PAGE_SIZE = 20;

const CONFLICT_LABELS: Record<string, string> = {
  curated_cluster_deleted: __('Curated cluster deleted remotely', 'alt-context'),
  curated_member_deleted: __('Curated member deleted remotely', 'alt-context'),
  member_cluster_reassignment: __('Member moved to another cluster remotely', 'alt-context'),
  version_conflict: __('Version conflict', 'alt-context'),
};

const formatTimestamp = (value: string | null): string => {
  if (!value) {
    return __('Unknown time', 'alt-context');
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
};

const formatConflictCode = (code: string): string => CONFLICT_LABELS[code] ?? code.replaceAll('_', ' ');

const getPayloadLabel = (payload: Record<string, unknown>): string | null => {
  if (typeof payload.label === 'string' && payload.label.trim() !== '') {
    return payload.label;
  }

  if (typeof payload.cluster_label === 'string' && payload.cluster_label.trim() !== '') {
    return payload.cluster_label;
  }

  return null;
};

const formatEntityLabel = (conflict: ConflictRecord): string => {
  const label = getPayloadLabel(conflict.local_payload) ?? getPayloadLabel(conflict.machine_payload);

  return label ? `${conflict.entity_key} (${label})` : conflict.entity_key;
};

const getUnsupportedExplanation = (conflict: ConflictRecord): string | null => {
  if (conflict.allowed_resolutions.includes('accepted')) {
    return null;
  }

  if (conflict.entity_type === 'person') {
    return __(
      'This person-side conflict only supports keeping the local version in Phase 4. Re-enqueue and retry remain available for the underlying outbox operation.',
      'alt-context',
    );
  }

  return __(
    'This compound topology conflict only supports keeping the local version in Phase 4. Re-enqueue and retry remain available for the underlying outbox operation.',
    'alt-context',
  );
};

const getResolutionButtonLabel = (choice: ConflictResolutionChoice): string =>
  choice === 'accepted' ? __('Accept machine version', 'alt-context') : __('Keep local version', 'alt-context');

const getAffectedMemberCount = (conflict: ConflictRecord): number | null => {
  const countKeys = ['member_count', 'attached_member_count'];
  for (const key of countKeys) {
    const machineValue = conflict.machine_payload[key];
    if (typeof machineValue === 'number' && Number.isFinite(machineValue)) {
      return machineValue;
    }

    const localValue = conflict.local_payload[key];
    if (typeof localValue === 'number' && Number.isFinite(localValue)) {
      return localValue;
    }
  }

  const localMemberIds = conflict.local_payload.member_ids;
  if (Array.isArray(localMemberIds)) {
    return localMemberIds.length;
  }

  const machineMemberIds = conflict.machine_payload.member_ids;
  if (Array.isArray(machineMemberIds)) {
    return machineMemberIds.length;
  }

  return null;
};

const getResolutionConfirmation = (conflict: ConflictRecord, choice: ConflictResolutionChoice): string => {
  if (choice === 'accepted' && conflict.conflict_code === 'curated_cluster_deleted') {
    const memberCount = getAffectedMemberCount(conflict);

    return memberCount !== null
      ? sprintf(
          __(
            'Accepting the machine version deletes the curated cluster and %d attached member rows still linked to it.',
            'alt-context',
          ),
          memberCount,
        )
      : __(
          'Accepting the machine version deletes the curated cluster and all member rows still attached to it.',
          'alt-context',
        );
  }

  if (choice === 'accepted' && conflict.outbox_id > 0 && conflict.entity_type === 'cluster') {
    if (typeof conflict.local_payload.target_cluster_id === 'string') {
      return __(
        'Accepting the machine version removes the temporary restored cluster, reassigns the listed members back to the machine target cluster, and discards the local revert operation.',
        'alt-context',
      );
    }

    return __(
      'Accepting the machine version resets all curated cluster fields to backend state, including label, person assignment, and dismissal state.',
      'alt-context',
    );
  }

  if (choice === 'accepted' && conflict.outbox_id > 0 && conflict.entity_type === 'member') {
    if (typeof conflict.local_payload.desired_cluster_id === 'string') {
      return __(
        'Accepting the machine version moves this identity back to the backend-selected cluster, removes the locally created cluster, and discards the local topology operation.',
        'alt-context',
      );
    }

    return __(
      'Accepting the machine version restores the member to the backend-selected cluster and discards the local topology operation.',
      'alt-context',
    );
  }

  return choice === 'accepted'
    ? __('Accept the machine version for this conflict?', 'alt-context')
    : __('Keep the local version for this conflict?', 'alt-context');
};

const getDisplayValue = (value: unknown): string => {
  if (value === null) {
    return 'null';
  }

  if (typeof value === 'undefined') {
    return __('Not set', 'alt-context');
  }

  if (typeof value === 'string') {
    return value;
  }

  return JSON.stringify(value);
};

interface DifferenceEntry {
  key: string;
  machineValue: string;
  localValue: string;
}

interface AcceptPreview {
  summary: string;
  payload?: Record<string, unknown>;
}

const getDifferenceEntries = (conflict: ConflictRecord): DifferenceEntry[] => {
  const keys = Array.from(
    new Set([...Object.keys(conflict.machine_payload), ...Object.keys(conflict.local_payload)]),
  ).sort((left, right) => left.localeCompare(right));

  return keys
    .filter((key) => JSON.stringify(conflict.machine_payload[key]) !== JSON.stringify(conflict.local_payload[key]))
    .map((key) => ({
      key,
      machineValue: getDisplayValue(conflict.machine_payload[key]),
      localValue: getDisplayValue(conflict.local_payload[key]),
    }));
};

const getAcceptMachinePreview = (conflict: ConflictRecord): AcceptPreview | null => {
  if (!conflict.allowed_resolutions.includes('accepted')) {
    return null;
  }

  if (conflict.conflict_code === 'curated_cluster_deleted') {
    return {
      summary: __('Accepting the machine version removes this cluster from the local projection.', 'alt-context'),
    };
  }

  if (conflict.conflict_code === 'curated_member_deleted') {
    return {
      summary: __('Accepting the machine version removes this member from the local projection.', 'alt-context'),
    };
  }

  if (conflict.conflict_code === 'member_cluster_reassignment') {
    return {
      summary: __('Accepting the machine version reassigns the member to the machine cluster and clears curation.', 'alt-context'),
      payload: {
        ...conflict.machine_payload,
        is_curated: false,
      },
    };
  }

  if (conflict.outbox_id > 0 && conflict.entity_type === 'cluster') {
    if (
      typeof conflict.local_payload.target_cluster_id === 'string' &&
      typeof conflict.local_payload.desired_source_cluster_id === 'string'
    ) {
      return {
        summary: __('Accepting the machine version removes the temporary restored cluster and moves the listed members back into the machine target cluster.', 'alt-context'),
        payload: {
          target_cluster_id: conflict.local_payload.target_cluster_id,
          removed_cluster_id: conflict.local_payload.desired_source_cluster_id,
          moved_identity_ids: conflict.local_payload.moved_identity_ids ?? [],
        },
      };
    }

    return {
      summary: __('Accepting the machine version resets the cluster to backend state and clears local curation guards.', 'alt-context'),
      payload: {
        ...conflict.machine_payload,
        label: null,
        person_id: null,
        curation_state: 'uncurated',
        is_user_confirmed: false,
      },
    };
  }

  if (conflict.outbox_id > 0 && conflict.entity_type === 'member') {
    if (typeof conflict.local_payload.desired_cluster_id === 'string') {
      return {
        summary: __('Accepting the machine version restores the member to the backend-selected cluster and removes the locally created cluster.', 'alt-context'),
        payload: {
          ...conflict.machine_payload,
          removed_cluster_id: conflict.local_payload.desired_cluster_id,
          is_curated: false,
        },
      };
    }

    return {
      summary: __('Accepting the machine version restores the member to the backend-selected cluster and clears local curation on that assignment.', 'alt-context'),
      payload: {
        ...conflict.machine_payload,
        is_curated: false,
      },
    };
  }

  return {
    summary: __('Accepting the machine version applies the backend payload on the next sync pull.', 'alt-context'),
    payload: conflict.machine_payload,
  };
};

interface ConflictDetailPanelProps {
  conflictId: number | null;
  pendingChoice: ConflictResolutionChoice | null;
  onRequestResolve: (choice: ConflictResolutionChoice) => void;
  isResolving: boolean;
}

const ConflictDetailPanel = ({
  conflictId,
  pendingChoice,
  onRequestResolve,
  isResolving,
}: ConflictDetailPanelProps): React.JSX.Element | null => {
  const detailQuery = useConflictDetail(conflictId);

  if (conflictId === null) {
    return null;
  }

  if (detailQuery.isLoading) {
    return <p>{__('Loading conflict detail…', 'alt-context')}</p>;
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <div className="acx-error-state">
        <p>{__('Unable to load conflict detail.', 'alt-context')}</p>
      </div>
    );
  }

  const { conflict } = detailQuery.data;
  const unsupportedExplanation = getUnsupportedExplanation(conflict);
  const differences = getDifferenceEntries(conflict);
  const acceptPreview = getAcceptMachinePreview(conflict);

  return (
    <div className="acx-workbench__panel">
      <h3>{__('Conflict Detail', 'alt-context')}</h3>
      <p>{formatConflictCode(conflict.conflict_code)}</p>
      <p>
        {sprintf(
          __('Entity: %1$s · Type: %2$s · Logged: %3$s', 'alt-context'),
          formatEntityLabel(conflict),
          conflict.entity_type,
          formatTimestamp(conflict.created_at),
        )}
      </p>
      {unsupportedExplanation ? <p>{unsupportedExplanation}</p> : null}
      {differences.length > 0 ? (
        <div>
          <h4>{__('Differing fields', 'alt-context')}</h4>
          <ul className="acx-dashboard__activity-list">
            {differences.map((difference) => (
              <li key={difference.key} className="acx-dashboard__activity-item">
                <div>
                  <strong>{difference.key}</strong>
                  <p>{sprintf(__('Machine: %s', 'alt-context'), difference.machineValue)}</p>
                  <p>{sprintf(__('Local: %s', 'alt-context'), difference.localValue)}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {acceptPreview ? (
        <div>
          <h4>{__('Accept machine preview', 'alt-context')}</h4>
          <p>{acceptPreview.summary}</p>
          {acceptPreview.payload ? <pre>{JSON.stringify(acceptPreview.payload, null, 2)}</pre> : null}
        </div>
      ) : null}
      <div className="acx-workbench__layout">
        <section aria-label={__('Machine payload', 'alt-context')}>
          <h4>{__('Machine payload', 'alt-context')}</h4>
          <pre>{JSON.stringify(conflict.machine_payload, null, 2)}</pre>
        </section>
        <section aria-label={__('Local payload', 'alt-context')}>
          <h4>{__('Local payload', 'alt-context')}</h4>
          <pre>{JSON.stringify(conflict.local_payload, null, 2)}</pre>
        </section>
      </div>
      {conflict.allowed_resolutions.length > 0 ? (
        <div className="acx-dashboard__actions">
          {conflict.allowed_resolutions.map((choice) => (
            <button
              key={choice}
              type="button"
              className="button button-secondary"
              onClick={() => {
                void onRequestResolve(choice);
              }}
              disabled={isResolving}
            >
              {pendingChoice === choice ? __('Confirm', 'alt-context') : getResolutionButtonLabel(choice)}
            </button>
          ))}
        </div>
      ) : (
        <p>{__('No resolution actions are available for this conflict.', 'alt-context')}</p>
      )}
      {pendingChoice ? <p>{getResolutionConfirmation(conflict, pendingChoice)}</p> : null}
    </div>
  );
};

export const ConflictInbox = (): React.JSX.Element => {
  const [offset, setOffset] = useState(0);
  const [selectedConflictIds, setSelectedConflictIds] = useState<number[]>([]);
  const [expandedConflictId, setExpandedConflictId] = useState<number | null>(null);
  const [pendingResolution, setPendingResolution] = useState<{
    conflictId: number;
    choice: ConflictResolutionChoice;
  } | null>(null);
  const [pendingBatchResolution, setPendingBatchResolution] = useState<ConflictResolutionChoice | null>(null);
  const [showSyncNow, setShowSyncNow] = useState(false);
  const [resolutionError, setResolutionError] = useState<string | null>(null);

  const conflictsQuery = useConflicts({ resolution_status: 'open', limit: PAGE_SIZE, offset });
  const resolveMutation = useResolveConflict();
  const syncTrigger = useSyncTrigger(false);

  const handleRequestResolve = async (choice: ConflictResolutionChoice): Promise<void> => {
    if (expandedConflictId === null) {
      return;
    }

    if (pendingResolution?.conflictId !== expandedConflictId || pendingResolution.choice !== choice) {
      setResolutionError(null);
      setPendingResolution({ conflictId: expandedConflictId, choice });
      return;
    }

    try {
      await resolveMutation.mutateAsync({
        id: expandedConflictId,
        request: { resolution_status: choice },
      });
      setPendingResolution(null);
      setResolutionError(null);
      setShowSyncNow(true);
    } catch {
      setShowSyncNow(false);
      setResolutionError(__('Unable to resolve this conflict. Please try again.', 'alt-context'));
    }
  };

  const handleToggleDetail = (conflictId: number): void => {
    setPendingBatchResolution(null);
    setPendingResolution(null);
    setResolutionError(null);
    setExpandedConflictId((current) => (current === conflictId ? null : conflictId));
  };

  const handleToggleSelection = (conflictId: number): void => {
    setPendingBatchResolution(null);
    setResolutionError(null);
    setSelectedConflictIds((current) =>
      current.includes(conflictId) ? current.filter((id) => id !== conflictId) : [...current, conflictId],
    );
  };

  if (conflictsQuery.isLoading) {
    return <section aria-label="Conflict inbox">{__('Loading conflicts…', 'alt-context')}</section>;
  }

  if (conflictsQuery.isError || !conflictsQuery.data) {
    return (
      <section aria-label="Conflict inbox">
        <div className="acx-error-state">
          <p>{__('Unable to load conflicts.', 'alt-context')}</p>
        </div>
      </section>
    );
  }

  const { items, total, limit } = conflictsQuery.data;
  const canPageBack = offset > 0;
  const canPageForward = offset + items.length < total;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = offset + items.length;
  const selectedConflicts = items.filter((conflict) => selectedConflictIds.includes(conflict.id));
  const canSelectAll = items.length > 0;
  const allOnPageSelected = canSelectAll && selectedConflicts.length === items.length;
  const batchAllowedResolutions =
    selectedConflicts.length > 0
      ? selectedConflicts.reduce<ConflictResolutionChoice[]>(
          (allowed, conflict) => allowed.filter((choice) => conflict.allowed_resolutions.includes(choice)),
          ['accepted', 'dismissed'],
        )
      : [];

  const handleToggleSelectAll = (): void => {
    setPendingBatchResolution(null);
    setResolutionError(null);
    setSelectedConflictIds(allOnPageSelected ? [] : items.map((conflict) => conflict.id));
  };

  const handleBatchResolve = async (choice: ConflictResolutionChoice): Promise<void> => {
    if (selectedConflicts.length === 0) {
      return;
    }

    if (pendingBatchResolution !== choice) {
      setResolutionError(null);
      setPendingResolution(null);
      setPendingBatchResolution(choice);
      return;
    }

    try {
      for (const conflict of selectedConflicts) {
        await resolveMutation.mutateAsync({
          id: conflict.id,
          request: { resolution_status: choice },
        });
      }
      setPendingBatchResolution(null);
      setPendingResolution(null);
      setResolutionError(null);
      setSelectedConflictIds([]);
      setShowSyncNow(true);
    } catch {
      setShowSyncNow(false);
      setResolutionError(__('Unable to resolve the selected conflicts. Please try again.', 'alt-context'));
    }
  };

  return (
    <section aria-label="Conflict inbox">
      <h3>{__('Open conflicts', 'alt-context')}</h3>
      <p>
        {sprintf(
          __('Showing %1$d-%2$d of %3$d open conflicts.', 'alt-context'),
          rangeStart,
          rangeEnd,
          total,
        )}
      </p>
      {canSelectAll ? (
        <div className="acx-dashboard__actions">
          <label>
            <input type="checkbox" checked={allOnPageSelected} onChange={handleToggleSelectAll} />
            {' '}
            {__('Select all conflicts on this page', 'alt-context')}
          </label>
          {selectedConflicts.length > 0 ? (
            <span>
              {sprintf(__('%d selected', 'alt-context'), selectedConflicts.length)}
            </span>
          ) : null}
          {batchAllowedResolutions.includes('accepted') ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                void handleBatchResolve('accepted');
              }}
              disabled={resolveMutation.isPending}
            >
              {pendingBatchResolution === 'accepted'
                ? __('Confirm accept selected', 'alt-context')
                : __('Accept machine for selected', 'alt-context')}
            </button>
          ) : null}
          {batchAllowedResolutions.includes('dismissed') ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                void handleBatchResolve('dismissed');
              }}
              disabled={resolveMutation.isPending}
            >
              {pendingBatchResolution === 'dismissed'
                ? __('Confirm keep local for selected', 'alt-context')
                : __('Keep local for selected', 'alt-context')}
            </button>
          ) : null}
        </div>
      ) : null}
      {showSyncNow ? (
        <div className="acx-notice acx-notice--info">
          <p>{__('Conflict resolved. Trigger sync now to converge local state with the backend.', 'alt-context')}</p>
          <button
            type="button"
            className="button button-primary"
            onClick={() => syncTrigger.mutate()}
            disabled={syncTrigger.isPending}
          >
            {__('Sync now', 'alt-context')}
          </button>
        </div>
      ) : null}
      {resolutionError ? (
        <div className="acx-notice acx-notice--warning">
          <p>{resolutionError}</p>
        </div>
      ) : null}
      {items.length === 0 ? (
        <p>{__('No open conflicts.', 'alt-context')}</p>
      ) : (
        <>
          <ul className="acx-dashboard__activity-list">
            {items.map((conflict) => {
              const isExpanded = expandedConflictId === conflict.id;

              return (
                <li key={conflict.id} className="acx-dashboard__activity-item">
                  <div>
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedConflictIds.includes(conflict.id)}
                        onChange={() => handleToggleSelection(conflict.id)}
                      />
                      {' '}
                      {__('Select conflict', 'alt-context')}
                    </label>
                    <strong>{formatEntityLabel(conflict)}</strong>
                    <p>{sprintf(__('Type: %s', 'alt-context'), conflict.entity_type)}</p>
                    <p>{formatConflictCode(conflict.conflict_code)}</p>
                    <p>{formatTimestamp(conflict.created_at)}</p>
                  </div>
                  <button
                    type="button"
                    className="button button-link"
                    onClick={() => handleToggleDetail(conflict.id)}
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? __('Hide detail', 'alt-context') : __('Review conflict', 'alt-context')}
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="acx-dashboard__actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                setSelectedConflictIds([]);
                setPendingBatchResolution(null);
                setOffset(offset - limit);
              }}
              disabled={!canPageBack}
            >
              {__('Previous', 'alt-context')}
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                setSelectedConflictIds([]);
                setPendingBatchResolution(null);
                setOffset(offset + limit);
              }}
              disabled={!canPageForward}
            >
              {__('Next', 'alt-context')}
            </button>
          </div>
        </>
      )}
      <ConflictDetailPanel
        conflictId={expandedConflictId}
        pendingChoice={pendingResolution?.conflictId === expandedConflictId ? pendingResolution.choice : null}
        onRequestResolve={(choice) => {
          void handleRequestResolve(choice);
        }}
        isResolving={resolveMutation.isPending}
      />
    </section>
  );
};

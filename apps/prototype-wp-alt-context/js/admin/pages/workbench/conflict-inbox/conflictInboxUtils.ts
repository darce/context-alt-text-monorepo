import { __, sprintf } from '@wordpress/i18n';

import type { ConflictRecord, ConflictResolutionChoice } from '../../../api/recognition';

const CONFLICT_LABELS: Record<string, string> = {
  curated_cluster_deleted: __('Curated cluster deleted remotely', 'alt-context'),
  curated_member_deleted: __('Curated member deleted remotely', 'alt-context'),
  member_cluster_reassignment: __('Member moved to another cluster remotely', 'alt-context'),
  person_name_conflict: __('Person name conflict', 'alt-context'),
  version_conflict: __('Version conflict', 'alt-context'),
  drift_conflict: __('Projection drift', 'alt-context'),
  backend_roster_regressed: __('Backend roster appears rolled back', 'alt-context'),
};

export interface DifferenceEntry {
  key: string;
  machineValue: string;
  localValue: string;
}

export interface AcceptPreview {
  summary: string;
  payload?: Record<string, unknown>;
}

export const formatTimestamp = (value: string | null): string => {
  if (!value) {
    return __('Unknown time', 'alt-context');
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
};

export const formatConflictCode = (code: string): string => CONFLICT_LABELS[code] ?? code.replaceAll('_', ' ');

export const getConflictTypeLabel = (conflict: ConflictRecord): string => {
  const conflictLabel = CONFLICT_LABELS[conflict.conflict_code];
  if (conflictLabel) {
    return conflictLabel;
  }

  if (conflict.entity_type === 'person') {
    return __('Person name conflict', 'alt-context');
  }

  return formatConflictCode(conflict.conflict_code);
};

const getPayloadLabel = (payload: Record<string, unknown>): string | null => {
  if (typeof payload.label === 'string' && payload.label.trim() !== '') {
    return payload.label;
  }

  if (typeof payload.cluster_label === 'string' && payload.cluster_label.trim() !== '') {
    return payload.cluster_label;
  }

  return null;
};

export const formatEntityLabel = (conflict: ConflictRecord): string => {
  const label = getPayloadLabel(conflict.local_payload) ?? getPayloadLabel(conflict.machine_payload);
  return label ? `${conflict.entity_key} (${label})` : conflict.entity_key;
};

export const getUnsupportedExplanation = (conflict: ConflictRecord): string | null => {
  if (conflict.allowed_resolutions.includes('accepted') || conflict.allowed_resolutions.includes('accept_backend')) {
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

export const getResolutionButtonLabel = (choice: ConflictResolutionChoice): string => {
  switch (choice) {
    case 'accepted':
    case 'accept_backend':
      return __('Accept backend version', 'alt-context');
    case 'dismissed':
      return __('Keep local version', 'alt-context');
    case 'merge':
      return __('Merge versions', 'alt-context');
    case 'restore_local':
      return __('Restore local curation', 'alt-context');
  }
};

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

export const getResolutionConfirmation = (conflict: ConflictRecord, choice: ConflictResolutionChoice): string => {
  if (choice === 'merge') {
    return __('Merge the backend and local versions for this conflict?', 'alt-context');
  }

  if (choice === 'restore_local') {
    return __(
      'Restore local curation by re-sending every affected curated cluster and member to the backend? Local data is preserved.',
      'alt-context',
    );
  }

  if ((choice === 'accepted' || choice === 'accept_backend') && conflict.conflict_code === 'backend_roster_regressed') {
    return __(
      'Accepting the backend roster deletes or reassigns every curated entity listed in this aggregate conflict.',
      'alt-context',
    );
  }

  if ((choice === 'accepted' || choice === 'accept_backend') && conflict.conflict_code === 'curated_cluster_deleted') {
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

  if (
    (choice === 'accepted' || choice === 'accept_backend') &&
    conflict.outbox_id > 0 &&
    conflict.entity_type === 'cluster'
  ) {
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

  if (
    (choice === 'accepted' || choice === 'accept_backend') &&
    conflict.outbox_id > 0 &&
    conflict.entity_type === 'member'
  ) {
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

  return choice === 'accepted' || choice === 'accept_backend'
    ? __('Accept the backend version for this conflict?', 'alt-context')
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

export const getDifferenceEntries = (conflict: ConflictRecord): DifferenceEntry[] => {
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

export const getAcceptBackendPreview = (conflict: ConflictRecord): AcceptPreview | null => {
  if (!conflict.allowed_resolutions.includes('accepted') && !conflict.allowed_resolutions.includes('accept_backend')) {
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
      summary: __(
        'Accepting the machine version reassigns the member to the machine cluster and clears curation.',
        'alt-context',
      ),
      payload: {
        ...conflict.machine_payload,
        is_curated: false,
      },
    };
  }

  if (conflict.conflict_code === 'backend_roster_regressed') {
    return {
      summary: __(
        'Accepting the backend roster applies every recorded deletion and reassignment across the affected curated entities.',
        'alt-context',
      ),
      payload: conflict.machine_payload,
    };
  }

  if (conflict.outbox_id > 0 && conflict.entity_type === 'cluster') {
    if (
      typeof conflict.local_payload.target_cluster_id === 'string' &&
      typeof conflict.local_payload.desired_source_cluster_id === 'string'
    ) {
      return {
        summary: __(
          'Accepting the machine version removes the temporary restored cluster and moves the listed members back into the machine target cluster.',
          'alt-context',
        ),
        payload: {
          target_cluster_id: conflict.local_payload.target_cluster_id,
          removed_cluster_id: conflict.local_payload.desired_source_cluster_id,
          moved_identity_ids: conflict.local_payload.moved_identity_ids ?? [],
        },
      };
    }

    return {
      summary: __(
        'Accepting the machine version resets the cluster to backend state and clears local curation guards.',
        'alt-context',
      ),
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
        summary: __(
          'Accepting the machine version restores the member to the backend-selected cluster and removes the locally created cluster.',
          'alt-context',
        ),
        payload: {
          ...conflict.machine_payload,
          removed_cluster_id: conflict.local_payload.desired_cluster_id,
          is_curated: false,
        },
      };
    }

    return {
      summary: __(
        'Accepting the machine version restores the member to the backend-selected cluster and clears local curation on that assignment.',
        'alt-context',
      ),
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

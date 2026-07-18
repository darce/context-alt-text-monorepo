/**
 * Hook for executing matched cluster actions with optional confirmation.
 *
 * Match ids are bare cluster ids (source-gated / unwrapped by callers). Person
 * option values never enter this path (PR-16).
 */

import React from 'react';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import { unwrapClusterOptionId } from './buildNamingOptions';
import type { ClusterGroup } from './types';
import type { SaveDialogAction } from './useClusterConfirmDialog';

interface ClusterMatchMutations {
  merge: (targetClusterId: string, targetLabel?: string, signal?: AbortSignal) => void;
  assignToCluster: (identityId: string, targetClusterId: string, signal?: AbortSignal) => void;
}

interface UseClusterMatchActionOptions {
  members: ClusterGroup['members'];
  editableClusterId: string | null;
  canSearchForMatch: boolean;
  options: ComboboxOption[];
  mutations: ClusterMatchMutations;
  requestConfirm: (action: SaveDialogAction, label: string) => Promise<boolean>;
}

const optionClusterId = (option: ComboboxOption): string | null => {
  const unwrapped = unwrapClusterOptionId(String(option.value));
  if (unwrapped) {
    return unwrapped;
  }
  // Legacy bare cluster id (tests / callers that have not migrated values yet)
  if (option.source === 'person') {
    return null;
  }
  return typeof option.value === 'string' && option.value.length > 0 ? option.value : null;
};

export const useClusterMatchAction = ({
  members,
  editableClusterId,
  canSearchForMatch,
  options,
  mutations,
  requestConfirm,
}: UseClusterMatchActionOptions) => {
  const isDangerousMerge = React.useCallback(
    (clusterId: string) => {
      const match = options.find((option) => optionClusterId(option) === clusterId);
      const targetMemberCount = (match?.identityCount ?? 0) as number;
      return targetMemberCount >= 5;
    },
    [options],
  );

  const runMatchedAction = React.useCallback(
    async (match: { id: string; label: string }, abortController: AbortController) => {
      const action: SaveDialogAction = canSearchForMatch ? 'assign' : 'merge';

      if (isDangerousMerge(match.id)) {
        const confirmed = await requestConfirm(action, match.label);
        if (!confirmed) {
          return false;
        }
      }

      if (abortController.signal.aborted) {
        return false;
      }

      if (editableClusterId) {
        mutations.merge(match.id, match.label, abortController.signal);
        return true;
      }

      for (const member of members) {
        mutations.assignToCluster(member.identity_id, match.id, abortController.signal);
      }
      return true;
    },
    [canSearchForMatch, editableClusterId, isDangerousMerge, members, mutations, requestConfirm],
  );

  return { runMatchedAction };
};

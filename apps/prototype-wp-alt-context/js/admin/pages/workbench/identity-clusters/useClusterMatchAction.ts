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

/** Cluster match from option or remote label lookup (optional member count for merge confirm). */
export interface ClusterLabelMatch {
  id: string;
  label: string;
  identityCount?: number;
  /** Pending suggestion id — when set, merge/assign resolve the suggestion by id (BR-16). */
  suggestionId?: string;
}

interface ClusterMatchMutations {
  merge: (
    targetClusterId: string,
    targetLabel?: string,
    signal?: AbortSignal,
    suggestionId?: string,
  ) => void;
  assignToCluster: (
    identityId: string,
    targetClusterId: string,
    signal?: AbortSignal,
    suggestionId?: string,
  ) => void;
}

interface UseClusterMatchActionOptions {
  members: ClusterGroup['members'];
  editableClusterId: string | null;
  canSearchForMatch: boolean;
  options: ComboboxOption[];
  mutations: ClusterMatchMutations;
  requestConfirm: (action: SaveDialogAction, label: string) => Promise<boolean>;
}

/** Merges of 5+ members require confirm; unknown size also requires confirm (FIX-3). */
export const DANGEROUS_MERGE_MEMBER_THRESHOLD = 5;

const optionClusterId = (option: ComboboxOption): string | null => unwrapClusterOptionId(String(option.value));

/**
 * Resolve member count for a match: prefer the match payload, then options.
 * Returns undefined when unknown (remote-only match with no count).
 */
export const resolveMatchMemberCount = (
  match: ClusterLabelMatch,
  options: readonly ComboboxOption[],
): number | undefined => {
  if (typeof match.identityCount === 'number') {
    return match.identityCount;
  }
  const option = options.find((entry) => optionClusterId(entry) === match.id);
  if (typeof option?.identityCount === 'number') {
    return option.identityCount;
  }
  return undefined;
};

/** Confirm when count is unknown or at/above the large-merge threshold (FIX-3). */
export const requiresMergeConfirm = (memberCount: number | undefined): boolean =>
  memberCount === undefined || memberCount >= DANGEROUS_MERGE_MEMBER_THRESHOLD;

export const useClusterMatchAction = ({
  members,
  editableClusterId,
  canSearchForMatch,
  options,
  mutations,
  requestConfirm,
}: UseClusterMatchActionOptions) => {
  const runMatchedAction = React.useCallback(
    async (match: ClusterLabelMatch, abortController: AbortController) => {
      const action: SaveDialogAction = canSearchForMatch ? 'assign' : 'merge';
      const memberCount = resolveMatchMemberCount(match, options);

      if (requiresMergeConfirm(memberCount)) {
        const confirmed = await requestConfirm(action, match.label);
        if (!confirmed) {
          return false;
        }
      }

      if (abortController.signal.aborted) {
        return false;
      }

      if (editableClusterId) {
        mutations.merge(match.id, match.label, abortController.signal, match.suggestionId);
        return true;
      }

      for (const member of members) {
        mutations.assignToCluster(
          member.identity_id,
          match.id,
          abortController.signal,
          match.suggestionId,
        );
      }
      return true;
    },
    [canSearchForMatch, editableClusterId, members, mutations, options, requestConfirm],
  );

  return { runMatchedAction };
};

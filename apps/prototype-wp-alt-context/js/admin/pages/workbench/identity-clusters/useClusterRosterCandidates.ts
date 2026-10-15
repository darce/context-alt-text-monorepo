import React from 'react';
import { useQuery } from '@tanstack/react-query';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import { queryKeys } from '../../../api/queryKeys';
import {
  fetchClusterRosterCandidates,
  ROSTER_CANDIDATES_TOP_K,
} from '../../../api/recognition/rosterCandidatesApi';
import type { RosterNamingEntry } from './buildNamingOptions';
import { buildRosterCandidateOptions } from './useClusterSuggestionsLoader';

export const useClusterRosterCandidates = ({
  clusterId,
  enabled,
  rosterEntries,
}: {
  clusterId?: string | null;
  enabled: boolean;
  rosterEntries: readonly RosterNamingEntry[];
}): {
  options: ComboboxOption[];
  isLoading: boolean;
  isError: boolean;
  retry: () => void;
} => {
  const id = clusterId?.trim() ?? '';
  const canQuery = enabled && Boolean(id);
  const query = useQuery({
    queryKey: queryKeys.clusters.rosterCandidates(id, ROSTER_CANDIDATES_TOP_K),
    queryFn: () => fetchClusterRosterCandidates(id, ROSTER_CANDIDATES_TOP_K),
    enabled: canQuery,
    staleTime: 30_000,
    retry: false,
  });
  const options = React.useMemo(
    () => canQuery ? buildRosterCandidateOptions(query.data?.candidates ?? [], rosterEntries) : [],
    [canQuery, query.data, rosterEntries],
  );
  const { refetch } = query;
  const retry = React.useCallback(() => {
    if (canQuery) {
      void refetch();
    }
  }, [canQuery, refetch]);

  return { options, isLoading: canQuery && query.isLoading, isError: canQuery && query.isError, retry };
};

/** Preserve the closest row's evidence and payload order when the roster overlaps. */
export const mergeRosterCandidateOptions = (
  closest: readonly ComboboxOption[],
  ordinary: readonly ComboboxOption[],
): ComboboxOption[] => {
  const values = new Set(closest.map((option) => option.value));
  return [...closest, ...ordinary.filter((option) => !values.has(option.value))];
};

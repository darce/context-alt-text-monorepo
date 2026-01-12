import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { listRosterEntries, type RosterEntry } from '../api/rosterApi';

export const useRosterEntries = () =>
  useQuery<RosterEntry[]>({
    queryKey: queryKeys.roster.entries(),
    queryFn: () => listRosterEntries(),
    refetchInterval: 60_000,
  });

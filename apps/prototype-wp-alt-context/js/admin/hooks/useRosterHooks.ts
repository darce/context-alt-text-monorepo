import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import {
  listRosterEntries,
  createPerson,
  updatePerson,
  deletePerson,
  type RosterEntry,
} from '../api/rosterApi';

export const useRosterEntries = () =>
  useQuery<RosterEntry[]>({
    queryKey: queryKeys.roster.entries(),
    queryFn: () => listRosterEntries(),
    refetchInterval: 60_000,
  });

export const useCreatePerson = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, tags }: { name: string; tags?: string[] }) => createPerson(name, tags),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.all });
    },
  });
};

export const useUpdatePerson = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name, tags }: { id: number; name?: string; tags?: string[] }) =>
      updatePerson(id, name, tags),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.all });
    },
  });
};

export const useDeletePerson = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deletePerson(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
  });
};

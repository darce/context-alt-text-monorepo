import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { listRosterEntries, createPerson, updatePerson, deletePerson, type RosterEntry } from '../api/rosterApi';

const rosterEntriesKey = queryKeys.roster.entries();

interface RosterMutationContext {
  previousEntries: RosterEntry[] | undefined;
  optimisticId?: number;
}

export const useRosterEntries = () =>
  useQuery<RosterEntry[]>({
    queryKey: rosterEntriesKey,
    queryFn: () => listRosterEntries(),
    refetchInterval: 60_000,
  });

export const useCreatePerson = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, tags }: { name: string; tags?: string[] }) => createPerson(name, tags),
    onMutate: async ({ name, tags }) => {
      await queryClient.cancelQueries({ queryKey: rosterEntriesKey });
      const previousEntries = queryClient.getQueryData<RosterEntry[]>(rosterEntriesKey);
      const optimisticEntry: RosterEntry = {
        id: -Date.now(),
        person_uuid: `optimistic-${Date.now()}`,
        name,
        tags: tags ?? [],
        cluster_count: 0,
        clusters: [],
        queue_memberships: [],
        updated_at: new Date().toISOString(),
        source_version: 0,
        projection_status: 'refreshing',
        projection_refreshed_at: null,
      };
      queryClient.setQueryData<RosterEntry[]>(rosterEntriesKey, (current) => [...(current ?? []), optimisticEntry]);
      return { previousEntries, optimisticId: optimisticEntry.id };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousEntries) {
        queryClient.setQueryData(rosterEntriesKey, context.previousEntries);
      }
    },
    onSuccess: (createdEntry, _variables, context) => {
      queryClient.setQueryData<RosterEntry[]>(rosterEntriesKey, (current) => {
        const previous = (current ?? []).find((entry) => entry.id === context?.optimisticId);
        const withoutOptimistic = (current ?? []).filter((entry) => entry.id !== context?.optimisticId);
        // Merge server fields into the previous (optimistic) row rather than
        // replacing: create_person returns a sparse acx_persons body with no
        // queue_memberships / clusters / projection_status.
        const merged: RosterEntry = {
          ...previous,
          ...createdEntry,
          queue_memberships: previous?.queue_memberships ?? [],
          clusters: previous?.clusters ?? [],
          projection_status: previous?.projection_status ?? 'refreshing',
        };
        return [...withoutOptimistic, merged];
      });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.all });
    },
  });
};

export const useUpdatePerson = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name, tags }: { id: number; name?: string; tags?: string[] }) => updatePerson(id, name, tags),
    onMutate: async ({ id, name, tags }): Promise<RosterMutationContext> => {
      await queryClient.cancelQueries({ queryKey: rosterEntriesKey });
      const previousEntries = queryClient.getQueryData<RosterEntry[]>(rosterEntriesKey);
      queryClient.setQueryData<RosterEntry[]>(rosterEntriesKey, (current) =>
        (current ?? []).map((entry) =>
          entry.id === id
            ? {
                ...entry,
                name: name ?? entry.name,
                tags: tags ?? entry.tags,
              }
            : entry,
        ),
      );
      return { previousEntries };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousEntries) {
        queryClient.setQueryData(rosterEntriesKey, context.previousEntries);
      }
    },
    onSuccess: (updatedEntry) => {
      queryClient.setQueryData<RosterEntry[]>(rosterEntriesKey, (current) =>
        (current ?? []).map((entry) =>
          entry.id === updatedEntry.id
            ? {
                // Merge server fields into the previous projected entry rather
                // than replacing: update_person returns a raw acx_persons row
                // with no queue_memberships, which would silently downgrade
                // needs-review → named until invalidation settles.
                ...entry,
                ...updatedEntry,
                queue_memberships: entry.queue_memberships ?? [],
                clusters: entry.clusters ?? [],
                projection_status: entry.projection_status,
              }
            : entry,
        ),
      );
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.all });
    },
  });
};

export const useDeletePerson = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deletePerson(id),
    onMutate: async (id): Promise<RosterMutationContext> => {
      await queryClient.cancelQueries({ queryKey: rosterEntriesKey });
      const previousEntries = queryClient.getQueryData<RosterEntry[]>(rosterEntriesKey);
      queryClient.setQueryData<RosterEntry[]>(rosterEntriesKey, (current) =>
        (current ?? []).filter((entry) => entry.id !== id),
      );
      return { previousEntries };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousEntries) {
        queryClient.setQueryData(rosterEntriesKey, context.previousEntries);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
  });
};

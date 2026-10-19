import type { QueryClient } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { invalidateDescriptionDrafts } from './invalidateDescriptionDrafts';

export const invalidateLabelSurfaces = (queryClient: QueryClient): void => {
  invalidateDescriptionDrafts(queryClient);
  void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.labels() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
  void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.projection.all });
  void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.namePending() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.roster.all });
};

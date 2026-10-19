import type { QueryClient } from '@tanstack/react-query';

/** Existing generations are stable; their current naming projection is derived. */
export const invalidateDescriptionDrafts = (queryClient: QueryClient): void => {
  void queryClient.invalidateQueries({ queryKey: ['describe-run-items'] });
  void queryClient.invalidateQueries({ queryKey: ['description-history'] });
};

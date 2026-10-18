import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { queryKeys } from '../../api/queryKeys';
import { invalidateLabelSurfaces } from '../invalidateLabelSurfaces';

describe('invalidateLabelSurfaces', () => {
  it('invalidates every query family that displays a person or cluster label', () => {
    const queryClient = new QueryClient();
    const labelSurfaceKeys = [
      queryKeys.media.identities(),
      queryKeys.clusters.labels(),
      queryKeys.clusters.all,
      queryKeys.roster.entries(),
      queryKeys.suggestions.projection.all,
      queryKeys.suggestions.mergePending(),
      queryKeys.suggestions.namePending(),
      queryKeys.roster.all,
    ];

    labelSurfaceKeys.forEach((queryKey) => queryClient.setQueryData(queryKey, {}));
    invalidateLabelSurfaces(queryClient);

    labelSurfaceKeys.forEach((queryKey) => {
      expect(queryClient.getQueryState(queryKey)?.isInvalidated, queryKey.join('.')).toBe(true);
    });

    queryClient.clear();
  });
});

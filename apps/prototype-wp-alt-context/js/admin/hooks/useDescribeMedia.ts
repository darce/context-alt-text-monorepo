import { useMutation } from '@tanstack/react-query';

import { describeMedia, type VisualFactsResponse } from '../api/describeApi';

/**
 * Describe a single attachment through the WP proxy (E19-1 S12). One-shot
 * mutation: callers `mutate(mediaId)` and read `data`/`error`/`isPending`.
 */
export const useDescribeMedia = () =>
  useMutation<VisualFactsResponse, Error, number>({
    mutationFn: (mediaId: number) => describeMedia(mediaId),
  });

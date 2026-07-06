import { useMutation } from '@tanstack/react-query';

import { describeMedia, type DescribeMediaWriteOptions, type VisualFactsResponse } from '../api/describeApi';

export type DescribeMediaMutationInput =
  | number
  | ({
      mediaId: number;
    } & DescribeMediaWriteOptions);

/**
 * Describe a single attachment through the WP proxy (E19-1 S12). One-shot
 * mutation: callers `mutate(mediaId)` or `mutate({ mediaId, writeAlt })`.
 */
export const useDescribeMedia = () =>
  useMutation<VisualFactsResponse, Error, DescribeMediaMutationInput>({
    mutationFn: (input: DescribeMediaMutationInput) => {
      if (typeof input === 'number') {
        return describeMedia(input);
      }
      return describeMedia(input.mediaId, {
        writeAlt: input.writeAlt,
        force: input.force ?? false,
      });
    },
  });

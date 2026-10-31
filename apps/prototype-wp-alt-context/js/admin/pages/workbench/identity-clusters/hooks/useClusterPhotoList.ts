import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../../api/queryKeys';
import { listRecognitionClusterPage } from '../../../../api/recognition/clusterApiQueries';
import type { ClusterListParams, ClusterPhotoListParams } from '../../../../api/recognition/types/cluster';

/** Producer-filtered pages; never derive photo counts from a preview or filter a loaded page. */
export const useClusterPhotoList = ({ limit = 20, search, labeled_only }: Omit<ClusterListParams, 'offset'> = {}) => {
  const scope = JSON.stringify([limit, search, labeled_only]);
  const [page, setPage] = useState<{ scope: string; offset: number; minimumPhotos?: number }>({ scope, offset: 0 });
  // Persist the reset before effects subscribe, including a return to an earlier search.
  if (page.scope !== scope) {
    setPage({ scope, minimumPhotos: page.minimumPhotos, offset: 0 });
  }
  const offset = page.scope === scope ? page.offset : 0;
  const params: ClusterPhotoListParams = { limit, offset };
  if (search !== undefined) {
    params.search = search;
  }
  if (labeled_only !== undefined) {
    params.labeled_only = labeled_only;
  }
  if (page.minimumPhotos !== undefined) {
    params.min_photos = page.minimumPhotos;
  }

  const query = useQuery({
    queryKey: queryKeys.clusters.list(params),
    queryFn: ({ signal }) => listRecognitionClusterPage(params, signal),
    // Do not show stale rows from the previous minimum while the new query is pending.
    placeholderData: undefined,
  });
  const hasNextPage = query.isSuccess && !query.isFetching && query.data.truncated;
  return {
    query,
    offset,
    minimumPhotos: page.minimumPhotos,
    hasNextPage,
    setMinimumPhotos: (minimumPhotos: number | undefined) => {
      if (
        minimumPhotos !== undefined &&
        (!Number.isInteger(minimumPhotos) || minimumPhotos < 1 || minimumPhotos > 2147483647)
      ) {
        throw new Error('min_photos must be an integer between 1 and 2147483647.');
      }
      setPage({ scope, minimumPhotos, offset: 0 });
    },
    nextPage: () => {
      if (hasNextPage) {
        setPage({ scope, minimumPhotos: page.minimumPhotos, offset: offset + query.data.limit });
      }
    },
    previousPage: () => setPage({ scope, minimumPhotos: page.minimumPhotos, offset: Math.max(0, offset - limit) }),
  };
};

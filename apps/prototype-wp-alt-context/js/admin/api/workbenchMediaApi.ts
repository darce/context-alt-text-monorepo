import type { WorkbenchMediaItem as WorkbenchMediaItemSchema } from './generated';
import { getConfig, getEndpoint } from './config';
import { fetchRequiredApi } from '../utils/http';

export interface WorkbenchMediaItem extends WorkbenchMediaItemSchema {
  thumbnailSrcset?: string | null;
  thumbnailSizes?: string | null;
  thumbnailDimensions?: {
    width: number | null;
    height: number | null;
  } | null;
}

export interface WorkbenchMediaResponse {
  items: WorkbenchMediaItem[];
  total: number;
  totalPages: number;
}

export type WorkbenchMediaStatus = 'all' | 'missing';

interface FetchWorkbenchMediaParams {
  page: number;
  perPage: number;
  search?: string;
  status?: WorkbenchMediaStatus;
}

const isWorkbenchMediaResponse = (value: unknown): value is WorkbenchMediaResponse =>
  Boolean(
    value &&
      typeof value === 'object' &&
      Array.isArray((value as WorkbenchMediaResponse).items) &&
      typeof (value as WorkbenchMediaResponse).total === 'number' &&
      typeof (value as WorkbenchMediaResponse).totalPages === 'number',
  );

export const fetchWorkbenchMedia = async ({
  page,
  perPage,
  search,
  status = 'all',
}: FetchWorkbenchMediaParams): Promise<WorkbenchMediaResponse> => {
  const endpoint = getEndpoint('workbenchMedia');
  const requestUrl = new URL(endpoint, window.location.origin);
  requestUrl.searchParams.set('page', String(page));
  requestUrl.searchParams.set('per_page', String(perPage));
  requestUrl.searchParams.set('status', status);

  if (search) {
    requestUrl.searchParams.set('search', search);
  }

  const payload = await fetchRequiredApi<unknown>(requestUrl.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });

  if (!isWorkbenchMediaResponse(payload)) {
    throw new Error('Workbench media response was malformed.');
  }

  return payload;
};

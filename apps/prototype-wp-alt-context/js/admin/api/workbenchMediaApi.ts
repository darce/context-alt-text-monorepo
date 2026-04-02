import type {
  WorkbenchMediaDetail as WorkbenchMediaDetailSchema,
  WorkbenchMediaItem as WorkbenchMediaItemSchema,
} from './generated';
import { getConfig, getEndpoint } from './config';
import { fetchRequiredApi } from '../utils/http';
import { createRecognitionTimeoutSignal } from './recognition/requestTimeout';

export interface WorkbenchMediaItem extends WorkbenchMediaItemSchema {
  thumbnailSrcset?: string | null;
  thumbnailSizes?: string | null;
  thumbnailDimensions?: {
    width: number | null;
    height: number | null;
  } | null;
  mimeType?: string | null;
  updatedAt?: string | null;
  dimensions?: {
    width: number | null;
    height: number | null;
  } | null;
  xmpPersistence?: Record<string, unknown> | null;
}

export interface WorkbenchMediaDetail extends WorkbenchMediaDetailSchema {}

export interface WorkbenchMediaResponse {
  items: WorkbenchMediaItem[];
  total: number;
  totalPages: number;
}

export interface WorkbenchMediaDetailResponse {
	 detailsByMedia: Record<string, WorkbenchMediaDetail>;
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

const isWorkbenchMediaDetailResponse = (value: unknown): value is WorkbenchMediaDetailResponse =>
  Boolean(
    value &&
      typeof value === 'object' &&
      'details_by_media' in value &&
      typeof (value as { details_by_media?: unknown }).details_by_media === 'object',
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
    signal: createRecognitionTimeoutSignal(15_000),
  });

  if (!isWorkbenchMediaResponse(payload)) {
    throw new Error('Workbench media response was malformed.');
  }

  return payload;
};

export const fetchWorkbenchMediaDetail = async (mediaIds: number[]): Promise<WorkbenchMediaDetailResponse> => {
  if (mediaIds.length === 0) {
    return { detailsByMedia: {} };
  }

  const endpoint = getEndpoint('workbenchMediaDetail');
  const requestUrl = new URL(endpoint, window.location.origin);
  mediaIds.forEach((mediaId) => {
    requestUrl.searchParams.append('ids[]', String(mediaId));
  });

  const payload = await fetchRequiredApi<unknown>(requestUrl.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(15_000),
  });

  if (!isWorkbenchMediaDetailResponse(payload)) {
    throw new Error('Workbench media detail response was malformed.');
  }

  return {
    detailsByMedia: (payload as { details_by_media: Record<string, WorkbenchMediaDetail> }).details_by_media,
  };
};

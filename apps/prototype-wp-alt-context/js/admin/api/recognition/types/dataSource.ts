export const DATA_SOURCE = {
  LOCAL_PROJECTION: 'local_projection',
  BACKEND_PROXY: 'backend_proxy',
  ENDPOINT_ERROR: 'endpoint_error',
  UNAVAILABLE: 'unavailable',
} as const;

export type DataSource = (typeof DATA_SOURCE)[keyof typeof DATA_SOURCE];

export const PROJECTION_STATUS = {
  AVAILABLE: 'available',
  BOOTSTRAPPING: 'bootstrapping',
  UNAVAILABLE: 'unavailable',
} as const;

export type ProjectionStatus = (typeof PROJECTION_STATUS)[keyof typeof PROJECTION_STATUS];

export const parseDataSource = (value: unknown): DataSource | null => {
  if (
    value === DATA_SOURCE.LOCAL_PROJECTION ||
    value === DATA_SOURCE.BACKEND_PROXY ||
    value === DATA_SOURCE.ENDPOINT_ERROR ||
    value === DATA_SOURCE.UNAVAILABLE
  ) {
    return value;
  }

  return null;
};

export const parseProjectionStatus = (value: unknown): ProjectionStatus | null => {
  if (
    value === PROJECTION_STATUS.AVAILABLE ||
    value === PROJECTION_STATUS.BOOTSTRAPPING ||
    value === PROJECTION_STATUS.UNAVAILABLE
  ) {
    return value;
  }

  return null;
};

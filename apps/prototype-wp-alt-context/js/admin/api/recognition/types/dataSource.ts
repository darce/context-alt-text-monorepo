export const DATA_SOURCE = {
  LOCAL_PROJECTION: 'local_projection',
  BACKEND_PROXY: 'backend_proxy',
  UNAVAILABLE: 'unavailable',
} as const;

export type DataSource = (typeof DATA_SOURCE)[keyof typeof DATA_SOURCE];

export const PROJECTION_STATUS = {
  AVAILABLE: 'available',
  BOOTSTRAPPING: 'bootstrapping',
  UNAVAILABLE: 'unavailable',
} as const;

export type ProjectionStatus = (typeof PROJECTION_STATUS)[keyof typeof PROJECTION_STATUS];

export const normalizeDataSource = (value: unknown, fallback: DataSource = DATA_SOURCE.BACKEND_PROXY): DataSource => {
  if (
    value === DATA_SOURCE.LOCAL_PROJECTION ||
    value === DATA_SOURCE.BACKEND_PROXY ||
    value === DATA_SOURCE.UNAVAILABLE
  ) {
    return value;
  }
  return fallback;
};

export const normalizeProjectionStatus = (
  value: unknown,
  fallback: ProjectionStatus = PROJECTION_STATUS.AVAILABLE,
): ProjectionStatus => {
  if (
    value === PROJECTION_STATUS.AVAILABLE ||
    value === PROJECTION_STATUS.BOOTSTRAPPING ||
    value === PROJECTION_STATUS.UNAVAILABLE
  ) {
    return value;
  }
  return fallback;
};

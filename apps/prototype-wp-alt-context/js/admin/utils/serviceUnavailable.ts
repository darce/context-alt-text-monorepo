import { __, sprintf } from '@wordpress/i18n';

export const UNAVAILABLE_REASON = {
  NOT_CONFIGURED: 'not_configured',
  API_KEY_MISSING: 'api_key_missing',
  CIRCUIT_OPEN: 'circuit_open',
  UPSTREAM_5XX: 'upstream_5xx',
  UPSTREAM_4XX: 'upstream_4xx',
  TIMEOUT: 'timeout',
  CONTRACT_MISMATCH: 'contract_mismatch',
} as const;

export const UNAVAILABLE_SERVICE = {
  RECOGNITION: 'recognition',
  SCENE: 'scene',
} as const;

export interface ServiceUnavailable {
  reason: string;
  service: string;
  http_status: number | null;
  retry_after_seconds: number | null;
  checked_at: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export const parseUnavailable = (value: unknown): ServiceUnavailable | null => {
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.reason !== 'string' || value.reason.trim() === '') {
    return null;
  }
  if (typeof value.service !== 'string' || value.service.trim() === '') {
    return null;
  }
  if (value.http_status !== null && value.http_status !== undefined) {
    if (typeof value.http_status !== 'number' || !Number.isFinite(value.http_status)) {
      return null;
    }
  }
  if (value.retry_after_seconds !== null && value.retry_after_seconds !== undefined) {
    if (typeof value.retry_after_seconds !== 'number' || !Number.isFinite(value.retry_after_seconds)) {
      return null;
    }
  }
  if (typeof value.checked_at !== 'string' || value.checked_at.trim() === '') {
    return null;
  }
  return {
    reason: value.reason,
    service: value.service,
    http_status: typeof value.http_status === 'number' ? value.http_status : null,
    retry_after_seconds: typeof value.retry_after_seconds === 'number' ? value.retry_after_seconds : null,
    checked_at: value.checked_at,
  };
};

const parseUnavailableFromRecord = (value: unknown): ServiceUnavailable | null => {
  if (!isRecord(value)) {
    return null;
  }
  const fromRoot = parseUnavailable(value.unavailable);
  if (fromRoot) {
    return fromRoot;
  }
  return isRecord(value.data) ? parseUnavailable(value.data.unavailable) : null;
};

export const readUnavailable = (source: unknown): ServiceUnavailable | null => {
  if (!isRecord(source)) {
    return null;
  }
  const direct = parseUnavailable(source.unavailable);
  if (direct) {
    return direct;
  }
  if (typeof source.bodyPreview !== 'string') {
    return null;
  }
  try {
    return parseUnavailableFromRecord(JSON.parse(source.bodyPreview));
  } catch {
    return null;
  }
};

export const unavailableServiceLabel = (service: string): string => {
  switch (service) {
    case UNAVAILABLE_SERVICE.RECOGNITION:
      return __('Recognition service', 'alt-context');
    case UNAVAILABLE_SERVICE.SCENE:
      return __('Description service', 'alt-context');
    default:
      return __('Service', 'alt-context');
  }
};

export type UnavailableReason = (typeof UNAVAILABLE_REASON)[keyof typeof UNAVAILABLE_REASON];

const UNAVAILABLE_REASON_COPY: Record<UnavailableReason, { why: string; fix: string }> = {
  [UNAVAILABLE_REASON.NOT_CONFIGURED]: {
    why: __('it is not configured', 'alt-context'),
    fix: __('Set the API URL in Settings.', 'alt-context'),
  },
  [UNAVAILABLE_REASON.API_KEY_MISSING]: {
    why: __('the API key is missing', 'alt-context'),
    fix: __('Add the API key in Settings.', 'alt-context'),
  },
  [UNAVAILABLE_REASON.CIRCUIT_OPEN]: {
    why: __('the circuit breaker is open', 'alt-context'),
    fix: __('Wait for the cooldown, then Retry.', 'alt-context'),
  },
  [UNAVAILABLE_REASON.UPSTREAM_5XX]: {
    why: __('the remote service is failing', 'alt-context'),
    fix: __('Retry in a moment. If it continues, check the service logs.', 'alt-context'),
  },
  [UNAVAILABLE_REASON.UPSTREAM_4XX]: {
    why: __('it rejected the request', 'alt-context'),
    fix: __('Check the API URL and key in Settings.', 'alt-context'),
  },
  [UNAVAILABLE_REASON.TIMEOUT]: {
    why: __('it did not respond in time', 'alt-context'),
    fix: __('Retry. If it continues, check that the host is reachable.', 'alt-context'),
  },
  [UNAVAILABLE_REASON.CONTRACT_MISMATCH]: {
    why: __('it returned a response this plugin does not recognize', 'alt-context'),
    fix: __('Confirm the plugin and service are on compatible versions.', 'alt-context'),
  },
};

const isUnavailableReason = (reason: string): reason is UnavailableReason =>
  (Object.values(UNAVAILABLE_REASON) as string[]).includes(reason);

export const unavailableReasonCopy = (reason: string): { why: string; fix: string } => {
  if (isUnavailableReason(reason)) {
    return UNAVAILABLE_REASON_COPY[reason];
  }
  return {
    why: sprintf(__('an unexpected error occurred (%s)', 'alt-context'), reason),
    fix: __('Retry. If it continues, check Settings and the service logs.', 'alt-context'),
  };
};

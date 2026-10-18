import { describe, expect, it, vi } from 'vitest';

import {
  parseUnavailable,
  readUnavailable,
  UNAVAILABLE_REASON,
  UNAVAILABLE_SERVICE,
  unavailableReasonCopy,
  unavailableServiceLabel,
  type UnavailableReason,
} from '../serviceUnavailable';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

const envelope = {
  reason: UNAVAILABLE_REASON.TIMEOUT,
  service: UNAVAILABLE_SERVICE.SCENE,
  http_status: 503,
  retry_after_seconds: 15,
  checked_at: '2026-09-18T14:03:22Z',
};

describe('parseUnavailable', () => {
  it('accepts a complete envelope and nulls optional numerics', () => {
    expect(parseUnavailable(envelope)).toEqual(envelope);
    expect(
      parseUnavailable({
        ...envelope,
        http_status: null,
        retry_after_seconds: null,
      }),
    ).toEqual({
      ...envelope,
      http_status: null,
      retry_after_seconds: null,
    });
  });

  it('rejects missing, empty, or non-finite fields without throwing', () => {
    expect(parseUnavailable(null)).toBeNull();
    expect(parseUnavailable('timeout')).toBeNull();
    expect(parseUnavailable({ ...envelope, reason: '  ' })).toBeNull();
    expect(parseUnavailable({ ...envelope, service: '' })).toBeNull();
    expect(parseUnavailable({ ...envelope, checked_at: '' })).toBeNull();
    expect(parseUnavailable({ ...envelope, http_status: Number.NaN })).toBeNull();
    expect(parseUnavailable({ ...envelope, retry_after_seconds: Number.POSITIVE_INFINITY })).toBeNull();
  });
});

describe('readUnavailable', () => {
  it('reads source.unavailable first, even when bodyPreview is truncated JSON', () => {
    const truncated = '{"code":"acx_service_unavailable","message":"x","data":{"status":503';
    expect(() => JSON.parse(truncated)).toThrow();
    expect(
      readUnavailable({
        unavailable: envelope,
        bodyPreview: truncated,
      }),
    ).toEqual(envelope);
  });

  it('falls back to nested data.unavailable inside bodyPreview', () => {
    expect(
      readUnavailable({
        bodyPreview: JSON.stringify({
          code: 'acx_service_unavailable',
          data: { status: 503, unavailable: envelope },
        }),
      }),
    ).toEqual(envelope);
  });

  it('returns null when bodyPreview JSON is truncated and no typed field is present', () => {
    const truncated = '{"code":"acx_service_unavailable","data":{"unavailable":{"reason":"timeout"';
    expect(
      readUnavailable({
        bodyPreview: truncated,
      }),
    ).toBeNull();
  });
});

const CLOSED_REASON_COPY: Record<UnavailableReason, { why: string; fix: string }> = {
  [UNAVAILABLE_REASON.NOT_CONFIGURED]: {
    why: 'it is not configured',
    fix: 'Set the API URL in Settings.',
  },
  [UNAVAILABLE_REASON.API_KEY_MISSING]: {
    why: 'the API key is missing',
    fix: 'Add the API key in Settings.',
  },
  [UNAVAILABLE_REASON.CIRCUIT_OPEN]: {
    why: 'the circuit breaker is open',
    fix: 'Wait for the cooldown, then Retry.',
  },
  [UNAVAILABLE_REASON.UPSTREAM_5XX]: {
    why: 'the remote service is failing',
    fix: 'Retry in a moment. If it continues, check the service logs.',
  },
  [UNAVAILABLE_REASON.UPSTREAM_4XX]: {
    why: 'it rejected the request',
    fix: 'Check the API URL and key in Settings.',
  },
  [UNAVAILABLE_REASON.TIMEOUT]: {
    why: 'it did not respond in time',
    fix: 'Retry. If it continues, check that the host is reachable.',
  },
  [UNAVAILABLE_REASON.CONTRACT_MISMATCH]: {
    why: 'it returned a response this plugin does not recognize',
    fix: 'Confirm the plugin and service are on compatible versions.',
  },
};

describe('unavailable copy', () => {
  it('names known services', () => {
    expect(unavailableServiceLabel(UNAVAILABLE_SERVICE.RECOGNITION)).toBe('Recognition service');
    expect(unavailableServiceLabel(UNAVAILABLE_SERVICE.SCENE)).toBe('Description service');
    expect(unavailableServiceLabel('other')).toBe('Service');
  });

  it.each(Object.entries(CLOSED_REASON_COPY) as [UnavailableReason, { why: string; fix: string }][])(
    'maps %s to specific actionable copy, not generic server-error text',
    (reason, expected) => {
      const copy = unavailableReasonCopy(reason);
      expect(copy).toEqual(expected);
      expect(copy.why).not.toMatch(/server error/i);
      expect(copy.why).not.toMatch(/unexpected error/i);
      expect(copy.fix).toMatch(/[A-Za-z]/);
    },
  );

  it('covers every closed-set reason with distinct why copy', () => {
    const reasons = Object.values(UNAVAILABLE_REASON);
    expect(reasons).toHaveLength(Object.keys(CLOSED_REASON_COPY).length);
    for (const reason of reasons) {
      expect(CLOSED_REASON_COPY[reason]).toBeDefined();
    }
    const whys = reasons.map((reason) => unavailableReasonCopy(reason).why);
    expect(new Set(whys).size).toBe(whys.length);
  });

  it('includes the reason code in the generic fallback', () => {
    expect(unavailableReasonCopy('mystery_code')).toEqual({
      why: 'an unexpected error occurred (mystery_code)',
      fix: 'Retry. If it continues, check Settings and the service logs.',
    });
  });
});

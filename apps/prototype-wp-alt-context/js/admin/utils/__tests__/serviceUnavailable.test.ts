import { describe, expect, it, vi } from 'vitest';

import {
  parseUnavailable,
  readUnavailable,
  UNAVAILABLE_REASON,
  UNAVAILABLE_SERVICE,
  unavailableReasonCopy,
  unavailableServiceLabel,
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

describe('unavailable copy', () => {
  it('names known services and reasons', () => {
    expect(unavailableServiceLabel(UNAVAILABLE_SERVICE.RECOGNITION)).toBe('Recognition service');
    expect(unavailableServiceLabel(UNAVAILABLE_SERVICE.SCENE)).toBe('Description service');
    expect(unavailableServiceLabel('other')).toBe('Service');
    expect(unavailableReasonCopy(UNAVAILABLE_REASON.CIRCUIT_OPEN)).toEqual({
      why: 'the circuit breaker is open',
      fix: 'Wait for the cooldown, then Retry.',
    });
  });

  it('includes the reason code in the generic fallback', () => {
    expect(unavailableReasonCopy('mystery_code')).toEqual({
      why: 'an unexpected error occurred (mystery_code)',
      fix: 'Retry. If it continues, check Settings and the service logs.',
    });
  });
});

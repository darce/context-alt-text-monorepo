import { describe, expect, expectTypeOf, it } from 'vitest';

import type { SettingsResponse } from '../settingsApi';
import { UrlRejectionReason } from '../settingsApi';

const SETTINGS_RESPONSE_KEYS = [
  'url',
  'url_source',
  'url_rejection_reason',
  'url_rejection_source',
  'url_rejection_value',
  'effective_target_url',
  'effective_target_mode',
  'recognition_source',
  'recognition_source_source',
  'api_key_set',
  'api_key_last4',
  'key_source',
  'tenant_id',
  'tenant_id_source',
  'tenant_paired',
  'alt_style',
  'recognition_enabled',
  'description_budget',
] as const;

describe('settings response contract', () => {
  const fixture: SettingsResponse = {
    url: 'https://api.example.com',
    url_source: 'option',
    url_rejection_reason: null,
    url_rejection_source: null,
    url_rejection_value: null,
    effective_target_url: 'https://api.example.com',
    effective_target_mode: 'service',
    recognition_source: 'service',
    recognition_source_source: 'option',
    api_key_set: true,
    api_key_last4: '****abcd',
    key_source: 'option',
    tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    tenant_id_source: 'option',
    tenant_paired: true,
    alt_style: 'alt_only',
    recognition_enabled: true,
    description_budget: {
      max_attempts: 3,
      usage: { attempts: 0, successes: 0, failures: 0, cost_total: 0 },
      recent_errors: [],
    },
  };

  it('matches the GET /acx/v1/settings envelope consumed by the admin UI', () => {
    expectTypeOf(fixture).toMatchTypeOf<SettingsResponse>();
    expect(Object.keys(fixture).sort()).toEqual([...SETTINGS_RESPONSE_KEYS].sort());
    expect(fixture.effective_target_mode).toBe('service');
    expect(fixture.recognition_source_source).toBe('option');
    // BR-138: pin the rejection fields on SettingsResponse itself — deleting them
    // from the type turns this expectTypeOf red under vitest typechecking.
    expectTypeOf(fixture.url_rejection_reason).toEqualTypeOf<
      SettingsResponse['url_rejection_reason']
    >();
    expectTypeOf(fixture.url_rejection_source).toEqualTypeOf<
      SettingsResponse['url_rejection_source']
    >();
    expectTypeOf(fixture.url_rejection_value).toEqualTypeOf<
      SettingsResponse['url_rejection_value']
    >();
  });

  it('includes BR-138 rejection fields and accepts a rejected-url fixture', () => {
    const rejected: SettingsResponse = {
      ...fixture,
      url: '',
      url_source: 'default',
      url_rejection_reason: UrlRejectionReason.NON_LOOPBACK_HTTP,
      url_rejection_source: 'option',
      url_rejection_value: 'http://10.0.0.5:8000',
      effective_target_url: '',
    };
    expectTypeOf(rejected).toMatchTypeOf<SettingsResponse>();
    expect(SETTINGS_RESPONSE_KEYS).toContain('url_rejection_reason');
    expect(SETTINGS_RESPONSE_KEYS).toContain('url_rejection_source');
    expect(SETTINGS_RESPONSE_KEYS).toContain('url_rejection_value');
    expect(rejected.url_rejection_reason).toBe('non_loopback_http');
  });
});

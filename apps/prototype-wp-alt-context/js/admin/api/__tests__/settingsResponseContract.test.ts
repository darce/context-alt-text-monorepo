import { describe, expect, expectTypeOf, it } from 'vitest';

import type { SettingsResponse } from '../settingsApi';

const SETTINGS_RESPONSE_KEYS = [
  'url',
  'url_source',
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
  'description_budget',
] as const;

describe('settings response contract', () => {
  const fixture: SettingsResponse = {
    url: 'https://api.example.com',
    url_source: 'option',
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
  });
});
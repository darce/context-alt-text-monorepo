import { describe, expect, it } from 'vitest';

import { TestConnectionOutcome, type TestConnectionResponse } from '../../../api/settingsApi';
import { HealthStatus } from '../settingsConstants';
import { healthStatusForService } from '../healthStatus';

describe('healthStatusForService', () => {
  it('returns not_checked when no probe result exists', () => {
    expect(healthStatusForService(null)).toBe(HealthStatus.NOT_CHECKED);
  });

  it('returns not_checked when the probe_mode is not the service probe', () => {
    const result = {
      outcome: TestConnectionOutcome.CONNECTED,
    } as TestConnectionResponse;

    expect(healthStatusForService(result)).toBe(HealthStatus.NOT_CHECKED);
  });

  it('maps a connected service probe to reachable', () => {
    const result: TestConnectionResponse = {
      outcome: TestConnectionOutcome.CONNECTED,
      probe_mode: 'service_auth',
    };

    expect(healthStatusForService(result)).toBe(HealthStatus.REACHABLE);
  });

  it('maps a failed service probe to unreachable', () => {
    const result: TestConnectionResponse = {
      outcome: TestConnectionOutcome.NETWORK_ERROR,
      probe_mode: 'service_auth',
    };

    expect(healthStatusForService(result)).toBe(HealthStatus.UNREACHABLE);
  });
});

import { describe, expect, it } from 'vitest';

import {
  RecognitionSource,
  TestConnectionOutcome,
  type TestConnectionResponse,
} from '../../../api/settingsApi';
import { HealthStatus } from '../settingsConstants';
import { healthStatusForTarget } from '../healthStatus';

describe('healthStatusForTarget', () => {
  it('returns not_checked when no probe result exists', () => {
    expect(healthStatusForTarget(RecognitionSource.LOCAL, null)).toBe(HealthStatus.NOT_CHECKED);
  });

  it('returns not_checked when probe_mode does not match the card target', () => {
    const result: TestConnectionResponse = {
      outcome: TestConnectionOutcome.CONNECTED,
      probe_mode: 'service_auth',
    };

    expect(healthStatusForTarget(RecognitionSource.LOCAL, result)).toBe(HealthStatus.NOT_CHECKED);
  });

  it('maps a matching connected probe to reachable', () => {
    const result: TestConnectionResponse = {
      outcome: TestConnectionOutcome.CONNECTED,
      probe_mode: 'local_liveness',
    };

    expect(healthStatusForTarget(RecognitionSource.LOCAL, result)).toBe(HealthStatus.REACHABLE);
  });

  it('maps a matching failed probe to unreachable', () => {
    const result: TestConnectionResponse = {
      outcome: TestConnectionOutcome.NETWORK_ERROR,
      probe_mode: 'service_auth',
    };

    expect(healthStatusForTarget(RecognitionSource.SERVICE, result)).toBe(HealthStatus.UNREACHABLE);
  });
});
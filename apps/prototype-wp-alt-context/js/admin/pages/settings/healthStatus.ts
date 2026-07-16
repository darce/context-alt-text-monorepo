import { TestConnectionOutcome, type TestConnectionResponse } from '../../api/settingsApi';
import { HealthStatus, type HealthStatusValue } from './settingsConstants';

// RECOG-1: single hosted-service target. The probe is always the authenticated
// service probe, so health maps directly from the latest test result.
export const healthStatusForService = (
  testResult: TestConnectionResponse | null,
): HealthStatusValue => {
  if (!testResult) {
    return HealthStatus.NOT_CHECKED;
  }

  if (testResult.probe_mode !== 'service_auth') {
    return HealthStatus.NOT_CHECKED;
  }

  return testResult.outcome === TestConnectionOutcome.CONNECTED
    ? HealthStatus.REACHABLE
    : HealthStatus.UNREACHABLE;
};

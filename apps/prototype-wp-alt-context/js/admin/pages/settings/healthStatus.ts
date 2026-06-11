import {
  RecognitionSource,
  TestConnectionOutcome,
  type RecognitionSourceValue,
  type TestConnectionResponse,
} from '../../api/settingsApi';
import { HealthStatus, type HealthStatusValue } from './settingsConstants';

export const healthStatusForTarget = (
  target: RecognitionSourceValue,
  testResult: TestConnectionResponse | null,
): HealthStatusValue => {
  if (!testResult) {
    return HealthStatus.NOT_CHECKED;
  }

  const probeMatchesTarget =
    (target === RecognitionSource.LOCAL && testResult.probe_mode === 'local_liveness') ||
    (target === RecognitionSource.SERVICE && testResult.probe_mode === 'service_auth');

  if (!probeMatchesTarget) {
    return HealthStatus.NOT_CHECKED;
  }

  return testResult.outcome === TestConnectionOutcome.CONNECTED
    ? HealthStatus.REACHABLE
    : HealthStatus.UNREACHABLE;
};
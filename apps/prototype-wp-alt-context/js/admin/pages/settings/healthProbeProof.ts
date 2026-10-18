import type { SettingsResponse, TestConnectionResponse } from '../../api/settingsApi';

// Client-only identity: neither displayed key metadata nor secret bytes identify
// a credential. The request object also keeps generations local to this mount.
export interface HealthProbeBinding {
  endpoint: string;
  tenant: string;
  credentialRevision: symbol;
  generation: number;
  request: object;
}

export const matchesHealthProbeTarget = (
  binding: HealthProbeBinding,
  settings: SettingsResponse | undefined,
): boolean => !!settings
  && binding.endpoint === settings.effective_target_url
  && binding.tenant === settings.tenant_id;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

export const hasInsightFaceProof = (
  result: TestConnectionResponse | null,
  binding: HealthProbeBinding,
): boolean => {
  if (!result || !binding.endpoint || result.outcome !== 'connected'
    || result.probe_mode !== 'service_auth' || result.status_code !== 200
    || result.probed_url !== `${binding.endpoint.replace(/\/+$/, '')}/health/detailed`
    || (result.tenant_id !== undefined && result.tenant_id !== binding.tenant)
    || result.pairing_error) {
    return false;
  }
  const body = result.body;
  return isRecord(body) && (body.status === 'ok' || body.status === 'degraded')
    && isRecord(body.model_cache) && body.model_cache.status === 'ok'
    && body.model_cache.profile === 'insightface';
};

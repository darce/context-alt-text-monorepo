import React, { useState, useEffect } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  fetchSettings,
  isTestConnectionOutcome,
  RecognitionSource,
  saveSettings,
  testConnection,
  TestConnectionOutcome,
  type RecognitionSourceValue,
  type SettingsResponse,
  type TestConnectionOutcomeValue,
  type TestConnectionProbeMode,
  type TestConnectionResponse,
} from '../api/settingsApi';
import { resetConfigCache } from '../api/config';
import { RadioGroup, RadioGroupItem } from '../../components/ui/radio-group';

type BannerTone = 'success' | 'warning' | 'error';

interface BannerCopy {
  tone: BannerTone;
  role: 'status' | 'alert';
  primary: string;
  remediation: string;
}

const unknownOutcomeBanner = (): BannerCopy => ({
  tone: 'error',
  role: 'alert',
  primary: __('Unexpected response from the recognition service.', 'alt-context'),
  remediation: __(
    'The probe returned a response the plugin does not recognize. Confirm the recognition service and plugin are on compatible versions.',
    'alt-context',
  ),
});

const renderBanner = (result: TestConnectionResponse): BannerCopy => {
  if (!isTestConnectionOutcome(result.outcome)) {
    return unknownOutcomeBanner();
  }
  const outcome: TestConnectionOutcomeValue = result.outcome;
  const isLocalProbe = result.probe_mode === 'local_liveness';
  switch (outcome) {
    case TestConnectionOutcome.CONNECTED:
      return {
        tone: 'success',
        role: 'status',
        primary: isLocalProbe
          ? __('Local recognition service is reachable.', 'alt-context')
          : __('Connection successful.', 'alt-context'),
        remediation: isLocalProbe
          ? __(
              'Scans route to this endpoint while recognition source is Local. Start the scan worker locally for processing.',
              'alt-context',
            )
          : __('The plugin authenticated against the recognition service and the pool is healthy.', 'alt-context'),
      };
    case TestConnectionOutcome.NOT_CONFIGURED:
      return {
        tone: 'warning',
        role: 'status',
        primary: __('No recognition URL configured.', 'alt-context'),
        remediation: __('Set the API URL above before testing.', 'alt-context'),
      };
    case TestConnectionOutcome.INVALID_KEY:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key rejected.', 'alt-context'),
        remediation: __(
          'The recognition service returned 401/403. Check the API Key field above, or ask an operator to re-issue the key.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.EXPIRED:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key expired.', 'alt-context'),
        remediation: __(
          'Ask an operator to rotate the key with the recognition CLI, then paste the new value here.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.REVOKED:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key revoked.', 'alt-context'),
        remediation: __(
          'This key has been revoked server-side. Request a fresh key and update the value above.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.TENANT_MISMATCH:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('Tenant mismatch.', 'alt-context'),
        remediation: __(
          'The API key belongs to a different site. Confirm the key was issued for this WordPress tenant.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.RATE_LIMITED: {
      const seconds = result.retry_after_seconds;
      const wait =
        typeof seconds === 'number' && seconds > 0
          ? sprintf(
              /* translators: %d is the number of seconds to wait before retrying. */
              __('Retry after %d seconds.', 'alt-context'),
              seconds,
            )
          : __('Retry after a few seconds.', 'alt-context');
      return {
        tone: 'warning',
        role: 'status',
        primary: __('Recognition service is rate limiting this site.', 'alt-context'),
        remediation: wait,
      };
    }
    case TestConnectionOutcome.SERVER_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('Recognition service returned a server error.', 'alt-context'),
        remediation: __(
          'Try again in a moment. If the problem persists, check the recognition service logs.',
          'alt-context',
        ),
      };
    case TestConnectionOutcome.NETWORK_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: isLocalProbe
          ? __('Could not reach the local recognition service.', 'alt-context')
          : __('Could not reach the recognition service.', 'alt-context'),
        remediation: isLocalProbe
          ? __(
              'Start the local description service (make serve), confirm the Local service URL matches its port, then test again.',
              'alt-context',
            )
          : __('Verify the API URL above and confirm the site can reach the recognition host.', 'alt-context'),
      };
    case TestConnectionOutcome.TLS_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('TLS handshake failed.', 'alt-context'),
        remediation: __(
          'The recognition service certificate could not be validated. Check the HTTPS endpoint and trust chain.',
          'alt-context',
        ),
      };
    default: {
      const exhaustive: never = outcome;
      return exhaustive;
    }
  }
};

const TONE_CLASS: Record<BannerTone, string> = {
  success: 'notice-success',
  warning: 'notice-warning',
  error: 'notice-error',
};

const SOURCE_LABELS: Record<string, string> = {
  constant: __('Set via wp-config.php constant', 'alt-context'),
  option: __('Saved in database', 'alt-context'),
  filter: __('Provided by a code filter', 'alt-context'),
  default: __('Not configured', 'alt-context'),
};

const isReadOnly = (source: string): boolean => source === 'constant' || source === 'filter';

export const SettingsPage = (): React.JSX.Element => {
  const queryClient = useQueryClient();

  const settingsQuery = useQuery<SettingsResponse>({
    queryKey: ['settings'],
    queryFn: fetchSettings,
  });

  const [url, setUrl] = useState('');
  const [localUrl, setLocalUrl] = useState('');
  const [recognitionSource, setRecognitionSource] = useState<RecognitionSourceValue>(RecognitionSource.SERVICE);
  const [apiKey, setApiKey] = useState('');
  const [saveMessage, setSaveMessage] = useState('');
  const [saveMessageTone, setSaveMessageTone] = useState<BannerTone>('success');
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(null);

  useEffect(() => {
    if (settingsQuery.data) {
      setUrl(settingsQuery.data.url);
      setLocalUrl(settingsQuery.data.local_url);
      setRecognitionSource(settingsQuery.data.recognition_source);
      setApiKey('');
    }
  }, [settingsQuery.data]);

  const syncLocalizedRouting = (settings: SettingsResponse): void => {
    if (!window.AltContextAdmin) {
      return;
    }

    window.AltContextAdmin.recognitionSource = settings.recognition_source;
    window.AltContextAdmin.effectiveTargetUrl = settings.effective_target_url;
    resetConfigCache();
  };

  const saveMutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: async () => {
      setSaveMessage(__('Settings saved.', 'alt-context'));
      setSaveMessageTone('success');
      setApiKey('');
      await queryClient.invalidateQueries({ queryKey: ['settings'] });
      const refreshed = await queryClient.fetchQuery({
        queryKey: ['settings'],
        queryFn: fetchSettings,
      });
      syncLocalizedRouting(refreshed);
    },
    onError: () => {
      setSaveMessage(__('Failed to save settings.', 'alt-context'));
      setSaveMessageTone('error');
    },
  });

  const testMutation = useMutation({
    mutationFn: testConnection,
    onSuccess: (data) => {
      setTestResult(data);
    },
    onError: () => {
      const probeMode: TestConnectionProbeMode =
        settingsQuery.data?.effective_target_mode === RecognitionSource.LOCAL ? 'local_liveness' : 'service_auth';
      setTestResult({ outcome: TestConnectionOutcome.NETWORK_ERROR, probe_mode: probeMode });
    },
  });

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaveMessage('');
    setSaveMessageTone('success');
    setTestResult(null);

    const payload: Record<string, string> = {};
    if (recognitionSource !== (settingsQuery.data?.recognition_source ?? RecognitionSource.LOCAL)) {
      payload.recognition_source = recognitionSource;
    }
    if (url !== (settingsQuery.data?.url ?? '')) {
      payload.url = url;
    }
    if (localUrl !== (settingsQuery.data?.local_url ?? '')) {
      payload.local_url = localUrl;
    }
    if (apiKey) {
      payload.api_key = apiKey;
    }

    if (Object.keys(payload).length === 0) {
      setSaveMessage(__('No changes to save.', 'alt-context'));
      setSaveMessageTone('warning');
      return;
    }

    saveMutation.mutate(payload);
  };

  const handleTest = () => {
    setTestResult(null);
    testMutation.mutate();
  };

  if (settingsQuery.isLoading) {
    return (
      <section className="acx-settings" aria-labelledby="acx-settings-title">
        <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
        <p>{__('Loading settings\u2026', 'alt-context')}</p>
      </section>
    );
  }

  if (settingsQuery.isError) {
    return (
      <section className="acx-settings" aria-labelledby="acx-settings-title">
        <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
        <p>{__('Failed to load settings.', 'alt-context')}</p>
      </section>
    );
  }

  const data = settingsQuery.data!;
  const sourceReadOnly = isReadOnly(data.recognition_source_source);
  const urlReadOnly = isReadOnly(data.url_source);
  const localUrlReadOnly = isReadOnly(data.local_url_source);
  const keyReadOnly = isReadOnly(data.key_source);
  const hasUnsavedRoutingChanges =
    recognitionSource !== data.recognition_source || localUrl !== data.local_url || url !== data.url;

  const activeModeLabel =
    data.effective_target_mode === RecognitionSource.LOCAL
      ? __('Local development service', 'alt-context')
      : __('Hosted recognition service', 'alt-context');

  const canTestActiveTarget = data.effective_target_mode === RecognitionSource.LOCAL || url.trim() !== '';

  return (
    <section className="acx-settings" aria-labelledby="acx-settings-title">
      <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
      <p className="description">
        {__('Configure the connection to the Alt Context recognition service.', 'alt-context')}
      </p>

      <div
        className="notice notice-info inline acx-settings__routing"
        style={{ marginBottom: '16px' }}
        data-testid="acx-effective-routing"
      >
        <p>
          <strong>{__('Active routing', 'alt-context')}</strong>
          {' — '}
          {activeModeLabel}
          {': '}
          <code>{data.effective_target_url}</code>
        </p>
        {hasUnsavedRoutingChanges ? (
          <p>{__('Save settings before scanning or testing so recognition traffic uses your edits.', 'alt-context')}</p>
        ) : null}
        {data.effective_target_mode === RecognitionSource.LOCAL && data.url ? (
          <p>
            {__(
              'Service URL and API key below are stored for service mode and are not used while Local is selected.',
              'alt-context',
            )}
          </p>
        ) : null}
      </div>

      <form onSubmit={handleSave} className="acx-settings__form">
        <table className="form-table" role="presentation">
          <tbody>
            <tr>
              <th scope="row">{__('Recognition Source', 'alt-context')}</th>
              <td>
                <fieldset>
                  <legend className="screen-reader-text">{__('Recognition Source', 'alt-context')}</legend>
                  <RadioGroup
                    aria-label={__('Recognition Source', 'alt-context')}
                    value={recognitionSource}
                    onValueChange={(value) => setRecognitionSource(value as RecognitionSourceValue)}
                    disabled={sourceReadOnly}
                  >
                    <label htmlFor="acx-settings-source-service" style={{ marginRight: '16px' }}>
                      <RadioGroupItem id="acx-settings-source-service" value={RecognitionSource.SERVICE} />{' '}
                      {__('Service', 'alt-context')}
                    </label>
                    <label htmlFor="acx-settings-source-local">
                      <RadioGroupItem id="acx-settings-source-local" value={RecognitionSource.LOCAL} />{' '}
                      {__('Local', 'alt-context')}
                    </label>
                  </RadioGroup>
                </fieldset>
                <p className="description">
                  {SOURCE_LABELS[data.recognition_source_source] ?? data.recognition_source_source}
                  {sourceReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
                </p>
              </td>
            </tr>
            <tr>
              <th scope="row">
                <label htmlFor="acx-settings-local-url">{__('Local service URL', 'alt-context')}</label>
              </th>
              <td>
                <input
                  id="acx-settings-local-url"
                  type="url"
                  className="regular-text"
                  value={localUrl}
                  onChange={(e) => setLocalUrl(e.target.value)}
                  readOnly={localUrlReadOnly}
                  placeholder="http://localhost:8000"
                />
                <p className="description">
                  {__(
                    'Used when recognition source is Local. Match the port from make serve (PORT env overrides the default 8000).',
                    'alt-context',
                  )}
                </p>
                <p className="description">
                  {SOURCE_LABELS[data.local_url_source] ?? data.local_url_source}
                  {localUrlReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
                </p>
              </td>
            </tr>
            <tr>
              <th scope="row">
                <label htmlFor="acx-settings-url">{__('Service API URL', 'alt-context')}</label>
              </th>
              <td>
                <input
                  id="acx-settings-url"
                  type="url"
                  className="regular-text"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  readOnly={urlReadOnly}
                  placeholder="https://api.altcontext.com"
                />
                <p className="description">
                  {__(
                    'Used when recognition source is Service (for example OCI at api.altcontext.com).',
                    'alt-context',
                  )}
                </p>
                <p className="description">
                  {SOURCE_LABELS[data.url_source] ?? data.url_source}
                  {urlReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
                </p>
              </td>
            </tr>
            <tr>
              <th scope="row">
                <label htmlFor="acx-settings-key">{__('API Key', 'alt-context')}</label>
              </th>
              <td>
                <input
                  id="acx-settings-key"
                  type="password"
                  className="regular-text"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  readOnly={keyReadOnly}
                  placeholder={data.api_key_set ? `Current: ${data.api_key_last4}` : __('Enter API key', 'alt-context')}
                />
                <p className="description">
                  {SOURCE_LABELS[data.key_source] ?? data.key_source}
                  {keyReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
                </p>
              </td>
            </tr>
          </tbody>
        </table>

        <p className="submit">
          <button
            type="submit"
            className="button button-primary"
            disabled={saveMutation.isPending || (sourceReadOnly && urlReadOnly && localUrlReadOnly && keyReadOnly)}
          >
            {saveMutation.isPending ? __('Saving\u2026', 'alt-context') : __('Save Settings', 'alt-context')}
          </button>
          <button
            type="button"
            className="button"
            onClick={handleTest}
            disabled={testMutation.isPending || !canTestActiveTarget || hasUnsavedRoutingChanges}
            style={{ marginLeft: '8px' }}
          >
            {testMutation.isPending ? __('Testing\u2026', 'alt-context') : __('Test active target', 'alt-context')}
          </button>
        </p>
      </form>

      {saveMessage && (
        <div className={`notice inline ${TONE_CLASS[saveMessageTone]}`} style={{ marginTop: '12px' }}>
          <p>{saveMessage}</p>
        </div>
      )}

      {testResult &&
        (() => {
          const banner = renderBanner(testResult);
          return (
            <div
              className={`notice inline ${TONE_CLASS[banner.tone]}`}
              role={banner.role}
              style={{ marginTop: '12px' }}
              data-testid="acx-test-connection-banner"
              data-outcome={testResult.outcome}
            >
              <p>{banner.primary}</p>
              <p>{banner.remediation}</p>
              {testResult.probed_url ? (
                <p>
                  {__('Probed', 'alt-context')}: <code>{testResult.probed_url}</code>
                </p>
              ) : null}
            </div>
          );
        })()}
    </section>
  );
};

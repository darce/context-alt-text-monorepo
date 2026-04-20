import React, { useState, useEffect } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  fetchSettings,
  saveSettings,
  testConnection,
  TestConnectionOutcome,
  type SettingsResponse,
  type TestConnectionOutcomeValue,
  type TestConnectionResponse,
} from '../api/settingsApi';

type BannerTone = 'success' | 'warning' | 'error';

interface BannerCopy {
  tone: BannerTone;
  role: 'status' | 'alert';
  primary: string;
  remediation: string;
}

const renderBanner = (result: TestConnectionResponse): BannerCopy => {
  const outcome: TestConnectionOutcomeValue = result.outcome;
  switch (outcome) {
    case TestConnectionOutcome.CONNECTED:
      return {
        tone: 'success',
        role: 'status',
        primary: __('Connection successful.', 'alt-context'),
        remediation: __(
          'The plugin authenticated against the recognition service and the pool is healthy.',
          'alt-context'
        ),
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
          'alt-context'
        ),
      };
    case TestConnectionOutcome.EXPIRED:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key expired.', 'alt-context'),
        remediation: __(
          'Ask an operator to rotate the key with the recognition CLI, then paste the new value here.',
          'alt-context'
        ),
      };
    case TestConnectionOutcome.REVOKED:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('API key revoked.', 'alt-context'),
        remediation: __(
          'This key has been revoked server-side. Request a fresh key and update the value above.',
          'alt-context'
        ),
      };
    case TestConnectionOutcome.TENANT_MISMATCH:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('Tenant mismatch.', 'alt-context'),
        remediation: __(
          'The API key belongs to a different site. Confirm the key was issued for this WordPress tenant.',
          'alt-context'
        ),
      };
    case TestConnectionOutcome.RATE_LIMITED: {
      const seconds = result.retry_after_seconds;
      const wait =
        typeof seconds === 'number' && seconds > 0
          ? sprintf(
              /* translators: %d is the number of seconds to wait before retrying. */
              __('Retry after %d seconds.', 'alt-context'),
              seconds
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
          'alt-context'
        ),
      };
    case TestConnectionOutcome.NETWORK_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('Could not reach the recognition service.', 'alt-context'),
        remediation: __(
          'Verify the API URL above and confirm the site can reach the recognition host.',
          'alt-context'
        ),
      };
    case TestConnectionOutcome.TLS_ERROR:
      return {
        tone: 'error',
        role: 'alert',
        primary: __('TLS handshake failed.', 'alt-context'),
        remediation: __(
          'The recognition service certificate could not be validated. Check the HTTPS endpoint and trust chain.',
          'alt-context'
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
  const [apiKey, setApiKey] = useState('');
  const [saveMessage, setSaveMessage] = useState('');
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(null);

  useEffect(() => {
    if (settingsQuery.data) {
      setUrl(settingsQuery.data.url);
      setApiKey('');
    }
  }, [settingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: () => {
      setSaveMessage(__('Settings saved.', 'alt-context'));
      setApiKey('');
      void queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: () => {
      setSaveMessage(__('Failed to save settings.', 'alt-context'));
    },
  });

  const testMutation = useMutation({
    mutationFn: testConnection,
    onSuccess: (data) => {
      setTestResult(data);
    },
    onError: () => {
      setTestResult({ outcome: TestConnectionOutcome.NETWORK_ERROR });
    },
  });

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaveMessage('');
    setTestResult(null);

    const payload: Record<string, string> = {};
    if (url !== (settingsQuery.data?.url ?? '')) {
      payload.url = url;
    }
    if (apiKey) {
      payload.api_key = apiKey;
    }

    if (Object.keys(payload).length === 0) {
      setSaveMessage(__('No changes to save.', 'alt-context'));
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
  const urlReadOnly = isReadOnly(data.url_source);
  const keyReadOnly = isReadOnly(data.key_source);

  return (
    <section className="acx-settings" aria-labelledby="acx-settings-title">
      <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
      <p className="description">
        {__('Configure the connection to the Alt Context recognition service.', 'alt-context')}
      </p>

      <form onSubmit={handleSave} className="acx-settings__form">
        <table className="form-table" role="presentation">
          <tbody>
            <tr>
              <th scope="row">
                <label htmlFor="acx-settings-url">{__('API URL', 'alt-context')}</label>
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
            disabled={saveMutation.isPending || (urlReadOnly && keyReadOnly)}
          >
            {saveMutation.isPending ? __('Saving\u2026', 'alt-context') : __('Save Settings', 'alt-context')}
          </button>
          <button
            type="button"
            className="button"
            onClick={handleTest}
            disabled={testMutation.isPending || url.trim() === ''}
            style={{ marginLeft: '8px' }}
          >
            {testMutation.isPending ? __('Testing\u2026', 'alt-context') : __('Test Connection', 'alt-context')}
          </button>
        </p>
      </form>

      {saveMessage && (
        <div className="notice notice-success inline" style={{ marginTop: '12px' }}>
          <p>{saveMessage}</p>
        </div>
      )}

      {testResult && (() => {
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
          </div>
        );
      })()}
    </section>
  );
};

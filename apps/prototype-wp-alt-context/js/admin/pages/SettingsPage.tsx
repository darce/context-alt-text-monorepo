import React, { useState, useEffect } from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  fetchSettings,
  saveSettings,
  testConnection,
  type SettingsResponse,
  type TestConnectionResponse,
} from '../api/settingsApi';

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
    onSuccess: (data) => {
      setSaveMessage(__('Settings saved.', 'alt-context'));
      setApiKey('');
      queryClient.invalidateQueries({ queryKey: ['settings'] });
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
      setTestResult({ connected: false, error: 'Request failed.' });
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
                  {urlReadOnly && (
                    <> &mdash; {__('read-only (override active)', 'alt-context')}</>
                  )}
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
                  {keyReadOnly && (
                    <> &mdash; {__('read-only (override active)', 'alt-context')}</>
                  )}
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
            disabled={testMutation.isPending}
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

      {testResult && (
        <div
          className={`notice inline ${testResult.connected ? 'notice-success' : 'notice-error'}`}
          style={{ marginTop: '12px' }}
        >
          <p>
            {testResult.connected
              ? __('Connection successful!', 'alt-context')
              : `${__('Connection failed.', 'alt-context')} ${testResult.error ?? `HTTP ${testResult.status_code}`}`}
          </p>
        </div>
      )}
    </section>
  );
};

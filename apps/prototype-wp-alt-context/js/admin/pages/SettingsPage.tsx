import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  fetchSettings,
  RecognitionSource,
  saveSettings,
  testConnection,
  TestConnectionOutcome,
  type RecognitionSourceValue,
  type SettingsResponse,
  type TestConnectionProbeMode,
} from '../api/settingsApi';
import { resetConfigCache } from '../api/config';
import { SettingsForm } from './settings/SettingsForm';
import { SettingsRoutingBanner } from './settings/SettingsRoutingBanner';
import { TestConnectionBannerView } from './settings/TestConnectionBannerView';
import { isReadOnly } from './settings/settingsConstants';
import { TONE_CLASS } from './settings/testConnectionBanner';
import { useSettingsPageState } from './settings/useSettingsPageState';

export const SettingsPage = (): React.JSX.Element => {
  const queryClient = useQueryClient();


  const settingsQuery = useQuery<SettingsResponse>({
    queryKey: ['settings'],
    queryFn: fetchSettings,
  });

  const { state, dispatch } = useSettingsPageState(settingsQuery.data);

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
      dispatch({ type: 'setSaveMessage', message: __('Settings saved.', 'alt-context'), tone: 'success' });
      dispatch({ type: 'setApiKey', value: '' });
      await queryClient.invalidateQueries({ queryKey: ['settings'] });
      const refreshed = await queryClient.fetchQuery({
        queryKey: ['settings'],
        queryFn: fetchSettings,
      });
      syncLocalizedRouting(refreshed);
    },
    onError: () => {
      dispatch({
        type: 'setSaveMessage',
        message: __('Failed to save settings.', 'alt-context'),
        tone: 'error',
      });
    },
  });

  const testMutation = useMutation({
    mutationFn: testConnection,
    onSuccess: (data) => {
      dispatch({ type: 'setTestResult', value: data });
    },
    onError: () => {
      const probeMode: TestConnectionProbeMode =
        settingsQuery.data?.effective_target_mode === RecognitionSource.LOCAL ? 'local_liveness' : 'service_auth';
      dispatch({
        type: 'setTestResult',
        value: { outcome: TestConnectionOutcome.NETWORK_ERROR, probe_mode: probeMode },
      });
    },
  });

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    dispatch({ type: 'clearSaveMessage' });
    dispatch({ type: 'clearTestResult' });

    const data = settingsQuery.data;
    const payload: Record<string, string> = {};
    if (state.recognitionSource !== (data?.recognition_source ?? RecognitionSource.LOCAL)) {
      payload.recognition_source = state.recognitionSource;
    }
    if (state.url !== (data?.url ?? '')) {
      payload.url = state.url;
    }
    if (state.localUrl !== (data?.local_url ?? '')) {
      payload.local_url = state.localUrl;
    }
    if (state.apiKey) {
      payload.api_key = state.apiKey;
    }

    if (Object.keys(payload).length === 0) {
      dispatch({
        type: 'setSaveMessage',
        message: __('No changes to save.', 'alt-context'),
        tone: 'warning',
      });
      return;
    }

    saveMutation.mutate(payload);
  };

  const handleTest = (target: RecognitionSourceValue) => {
    dispatch({ type: 'clearTestResult' });
    testMutation.mutate({ probe_target: target });
  };

  const handleConfirmTenantPairing = () => {
    testMutation.mutate({ confirm_tenant_pairing: true });
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
    state.recognitionSource !== data.recognition_source ||
    state.localUrl !== data.local_url ||
    state.url !== data.url;
  return (
    <section className="acx-settings" aria-labelledby="acx-settings-title">
      <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
      <p className="description">
        {__('Configure the connection to the Alt Context recognition service.', 'alt-context')}
      </p>

      <SettingsRoutingBanner />

      <SettingsForm
        data={data}
        url={state.url}
        localUrl={state.localUrl}
        recognitionSource={state.recognitionSource}
        apiKey={state.apiKey}
        sourceReadOnly={sourceReadOnly}
        urlReadOnly={urlReadOnly}
        localUrlReadOnly={localUrlReadOnly}
        keyReadOnly={keyReadOnly}
        savePending={saveMutation.isPending}
        testPending={testMutation.isPending}
        hasUnsavedRoutingChanges={hasUnsavedRoutingChanges}
        testResult={state.testResult}
        onUrlChange={(value) => dispatch({ type: 'setUrl', value })}
        onLocalUrlChange={(value) => dispatch({ type: 'setLocalUrl', value })}
        onRecognitionSourceChange={(value) => dispatch({ type: 'setRecognitionSource', value })}
        onApiKeyChange={(value) => dispatch({ type: 'setApiKey', value })}
        onSave={handleSave}
        onTest={handleTest}
        onFocusServiceUrl={() => {
          dispatch({ type: 'setRecognitionSource', value: RecognitionSource.SERVICE });
          document.getElementById('acx-settings-url')?.focus();
        }}
      />

      {state.saveMessage ? (
        <div className={`notice inline ${TONE_CLASS[state.saveMessageTone]}`} style={{ marginTop: '12px' }}>
          <p>{state.saveMessage}</p>
        </div>
      ) : null}

      {state.testResult ? (
        <TestConnectionBannerView
          testResult={state.testResult}
          onConfirmTenantPairing={handleConfirmTenantPairing}
          confirmPending={testMutation.isPending}
        />
      ) : null}
    </section>
  );
};
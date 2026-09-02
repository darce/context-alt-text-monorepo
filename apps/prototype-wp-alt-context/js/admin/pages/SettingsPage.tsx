import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  fetchSettings,
  saveSettings,
  testConnection,
  SettingsSaveResult,
  TestConnectionOutcome,
  type SaveSettingsPayload,
  type SaveSettingsResponse,
  type SettingsResponse,
} from '../api/settingsApi';
import { resetConfigCache } from '../api/config';
import { queryKeys } from '../api/queryKeys';
import { resolveWpErrorMessage } from '../api/wpErrorMessage';
import { toDashboard } from '../navigation/appLinks';
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
    onSuccess: async (data: SaveSettingsResponse) => {
      // R23-BR-14: backend may return 200 with result partial/error when some
      // options did not persist. Do not render "Settings saved." unless ok —
      // a corrected backend that still paints success on the frontend has
      // fixed nothing an operator can see.
      if (data.result !== SettingsSaveResult.OK) {
        const failedFields = Array.isArray(data.failed) && data.failed.length > 0
          ? data.failed.join(', ')
          : __('one or more fields', 'alt-context');
        dispatch({
          type: 'setSaveMessage',
          message: `${__('Could not save settings.', 'alt-context')} (${failedFields})`,
          tone: 'error',
        });
        // Refresh so the form reflects what actually landed (partial success).
        await queryClient.invalidateQueries({ queryKey: ['settings'] });
        const refreshedOnFail = await queryClient.fetchQuery({
          queryKey: ['settings'],
          queryFn: fetchSettings,
        });
        syncLocalizedRouting(refreshedOnFail);
        return;
      }

      dispatch({ type: 'setSaveMessage', message: __('Settings saved.', 'alt-context'), tone: 'success' });
      dispatch({ type: 'setApiKey', value: '' });
      await queryClient.invalidateQueries({ queryKey: ['settings'] });
      // A saved URL/key may repair the recognition breaker; refetch sync health
      // so the degraded/offline banner clears without waiting for its 15s poll.
      await queryClient.invalidateQueries({ queryKey: queryKeys.sync.health() });
      const refreshed = await queryClient.fetchQuery({
        queryKey: ['settings'],
        queryFn: fetchSettings,
      });
      syncLocalizedRouting(refreshed);
    },
    onError: (error) => {
      dispatch({
        type: 'setSaveMessage',
        message: resolveWpErrorMessage(error, __('Failed to save settings.', 'alt-context')),
        tone: 'error',
      });
    },
  });

  const testMutation = useMutation({
    mutationFn: testConnection,
    onSuccess: (data) => {
      dispatch({ type: 'setTestResult', value: data });
      // A reachable probe (or an adopted tenant) means the service is back;
      // refetch sync health so the offline banner clears immediately.
      void queryClient.invalidateQueries({ queryKey: queryKeys.sync.health() });
    },
    // Outcome enum maps to fixed banner copy; it cannot carry a free-form server
    // message without a new enum member ([sr-007]). Leave NETWORK_ERROR as the
    // transport-failure stand-in — see REPORT.md.
    onError: () => {
      dispatch({
        type: 'setTestResult',
        value: { outcome: TestConnectionOutcome.NETWORK_ERROR, probe_mode: 'service_auth' },
      });
    },
  });

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    dispatch({ type: 'clearSaveMessage' });
    dispatch({ type: 'clearTestResult' });

    const data = settingsQuery.data;
    if (!data) {
      // Save is only reachable from the loaded form (render guards isLoading/
      // isError below); bail defensively so the diff never derefs undefined.
      return;
    }
    const payload: SaveSettingsPayload = {};
    if (state.url !== (data?.url ?? '')) {
      payload.url = state.url;
    }
    if (state.apiKey) {
      payload.api_key = state.apiKey;
    }
    const descriptionBudgetMaxAttempts = Number.parseInt(state.descriptionBudgetMaxAttempts, 10);
    if (
      Number.isFinite(descriptionBudgetMaxAttempts) &&
      descriptionBudgetMaxAttempts !== data.description_budget.max_attempts
    ) {
      payload.description_budget = { max_attempts: descriptionBudgetMaxAttempts };
    }
    if (state.recognitionEnabled !== data.recognition_enabled) {
      payload.recognition_enabled = state.recognitionEnabled;
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

  const handleTest = () => {
    dispatch({ type: 'clearTestResult' });
    testMutation.mutate({});
  };

  const handleConfirmTenantPairing = () => {
    testMutation.mutate({ confirm_tenant_pairing: true });
  };

  const settingsErrorMessage = settingsQuery.isLoadingError
    ? __('Failed to load settings.', 'alt-context')
    : settingsQuery.isRefetchError
      ? __('Failed to refresh settings.', 'alt-context')
      : '';
  const errorLiveRegion = (
    <div
      className={settingsErrorMessage ? 'notice inline notice-error' : undefined}
      role="alert"
      aria-live="assertive"
      data-testid="acx-settings-query-error"
    >
      {settingsErrorMessage ? <p>{settingsErrorMessage}</p> : null}
    </div>
  );

  if (settingsQuery.isLoading) {
    return (
      <section className="acx-settings" aria-labelledby="acx-settings-page-title">
        <h1 id="acx-settings-page-title" className="acx-dashboard__title">
          {__('Settings', 'alt-context')}
        </h1>
        <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
        {errorLiveRegion}
        <p>{__('Loading settings…', 'alt-context')}</p>
      </section>
    );
  }

  if (settingsQuery.isLoadingError) {
    return (
      <section className="acx-settings" aria-labelledby="acx-settings-page-title">
        <h1 id="acx-settings-page-title" className="acx-dashboard__title">
          {__('Settings', 'alt-context')}
        </h1>
        <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
        {errorLiveRegion}
        <div className="acx-dashboard__actions">
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={() => void settingsQuery.refetch()}
          >
            {__('Retry', 'alt-context')}
          </button>
          <a className="acx-button acx-button--secondary" href={toDashboard()}>
            {__('Back to Dashboard', 'alt-context')}
          </a>
        </div>
      </section>
    );
  }

  const data = settingsQuery.data!;
  const urlReadOnly = isReadOnly(data.url_source);
  const keyReadOnly = isReadOnly(data.key_source);
  const hasUnsavedRoutingChanges = state.url !== data.url;
  return (
    <section className="acx-settings" aria-labelledby="acx-settings-page-title">
      <h1 id="acx-settings-page-title" className="acx-dashboard__title">
        {__('Settings', 'alt-context')}
      </h1>
      <h2 id="acx-settings-title">{__('Recognition API Settings', 'alt-context')}</h2>
      {errorLiveRegion}
      <p className="description">
        {__('Configure the connection to the Alt Context recognition service.', 'alt-context')}
      </p>

      <SettingsRoutingBanner />

      <SettingsForm
        values={{
          data,
          url: state.url,
          apiKey: state.apiKey,
          descriptionBudgetMaxAttempts: state.descriptionBudgetMaxAttempts,
          recognitionEnabled: state.recognitionEnabled,
          urlReadOnly,
          keyReadOnly,
        }}
        status={{
          savePending: saveMutation.isPending,
          testPending: testMutation.isPending,
          hasUnsavedRoutingChanges,
          testResult: state.testResult,
        }}
        actions={{
          onUrlChange: (value) => dispatch({ type: 'setUrl', value }),
          onApiKeyChange: (value) => dispatch({ type: 'setApiKey', value }),
          onDescriptionBudgetMaxAttemptsChange: (value) =>
            dispatch({ type: 'setDescriptionBudgetMaxAttempts', value }),
          onRecognitionEnabledChange: (value) => dispatch({ type: 'setRecognitionEnabled', value }),
          onSave: handleSave,
          onTest: handleTest,
          onFocusServiceUrl: () => {
            document.getElementById('acx-settings-url')?.focus();
          },
        }}
      />

      {state.saveMessage ? (
        <div
          className={`notice inline ${TONE_CLASS[state.saveMessageTone]}`}
          role={state.saveMessageTone === 'error' ? 'alert' : 'status'}
          style={{ marginTop: '12px' }}
          data-testid="acx-settings-save-message"
        >
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

import React, { useEffect, useRef } from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';

import {
  fetchSettings,
  saveSettings,
  testConnection,
  SettingsSaveResult,
  TestConnectionOutcome,
  type SaveSettingsPayload,
  type SaveSettingsResponse,
  type SettingsResponse,
  type TestConnectionResponse,
} from '../api/settingsApi';
import { resetConfigCache } from '../api/config';
import { queryKeys } from '../api/queryKeys';
import { resolveWpErrorMessage } from '../api/wpErrorMessage';
import { toDashboard } from '../navigation/appLinks';
import { RetentionSection } from './RetentionPage';
import { SettingsForm } from './settings/SettingsForm';
import { SettingsRoutingBanner } from './settings/SettingsRoutingBanner';
import { TestConnectionBannerView } from './settings/TestConnectionBannerView';
import { GpuControlCard } from './settings/GpuControlCard';
import { isReadOnly } from './settings/settingsConstants';
import { TONE_CLASS } from './settings/testConnectionBanner';
import { useSettingsPageState } from './settings/useSettingsPageState';

const SETTINGS_SECTION_RETENTION_ID = 'acx-settings-section-retention';
const SETTINGS_SECTION_RETENTION_HEADING_ID = 'acx-retention-title';

interface SettingsFormSnapshot {
  url: string;
  apiKey: string;
  descriptionBudgetMaxAttempts: string;
  recognitionEnabled: boolean;
  allowPersonNames: boolean | null;
}

const sectionFromLocation = (search: string, hash: string): string | null => {
  const fromSearch = new URLSearchParams(search).get('section');
  if (fromSearch) {
    return fromSearch;
  }
  const hashQuery = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : '';
  const fromHash = new URLSearchParams(hashQuery).get('section');
  if (fromHash) {
    return fromHash;
  }
  return new URLSearchParams(window.location.search).get('section');
};

export const SettingsPage = (): React.JSX.Element => {
  const queryClient = useQueryClient();
  const location = useLocation();
  const automaticHealthCheckStarted = useRef(false);
  const healthProbeGeneration = useRef(0);
  const healthProbeMetadata = useRef(new WeakMap<object, { generation: number; afterRoutingSave: boolean }>());
  const routingSavePending = useRef(false);
  const routingSaveFeedback = useRef(false);
  const queuedSaveSnapshot = useRef<SettingsFormSnapshot | null>(null);

  const settingsQuery = useQuery<SettingsResponse>({
    queryKey: queryKeys.settings.all,
    queryFn: fetchSettings,
  });

  useEffect(() => {
    if (settingsQuery.isLoading || settingsQuery.isLoadingError) {
      return;
    }
    if (sectionFromLocation(location.search, location.hash) !== 'retention') {
      return;
    }
    document.getElementById(SETTINGS_SECTION_RETENTION_ID)?.scrollIntoView();
    document.getElementById(SETTINGS_SECTION_RETENTION_HEADING_ID)?.focus();
  }, [location.search, location.hash, settingsQuery.isLoading, settingsQuery.isLoadingError]);

  const { state, dispatch } = useSettingsPageState(settingsQuery.data);

  const syncLocalizedRouting = (settings: SettingsResponse): void => {
    if (!window.AltContextAdmin) {
      return;
    }

    window.AltContextAdmin.recognitionSource = settings.recognition_source;
    window.AltContextAdmin.effectiveTargetUrl = settings.effective_target_url;
    resetConfigCache();
  };

  const applyHealthProbeSuccess = (data: TestConnectionResponse, generation: number): void => {
    if (generation !== healthProbeGeneration.current) {
      return;
    }
    dispatch({ type: 'setTestResult', value: data });
    // A reachable probe (or an adopted tenant) means the service is back;
    // refetch sync health so the offline banner clears immediately.
    void queryClient.invalidateQueries({ queryKey: queryKeys.sync.health() });
  };

  const applyHealthProbeError = (generation: number): void => {
    if (generation !== healthProbeGeneration.current) {
      return;
    }
    dispatch({
      type: 'setTestResult',
      value: { outcome: TestConnectionOutcome.NETWORK_ERROR, probe_mode: 'service_auth' },
    });
  };

  const clearRoutingCheckFeedback = (): void => {
    if (routingSaveFeedback.current) {
      routingSaveFeedback.current = false;
      dispatch({ type: 'clearSaveMessage' });
    }
  };

  const captureFormSnapshot = (): SettingsFormSnapshot => ({
    url: state.url,
    apiKey: state.apiKey,
    descriptionBudgetMaxAttempts: state.descriptionBudgetMaxAttempts,
    recognitionEnabled: state.recognitionEnabled,
    allowPersonNames: state.allowPersonNames,
  });

  const buildSavePayload = (
    values: SettingsFormSnapshot,
    data: SettingsResponse,
  ): SaveSettingsPayload => {
    const payload: SaveSettingsPayload = {};
    if (values.url !== (data.url ?? '')) {
      payload.url = values.url;
    }
    if (values.apiKey) {
      payload.api_key = values.apiKey;
    }
    const descriptionBudgetMaxAttempts = Number.parseInt(values.descriptionBudgetMaxAttempts, 10);
    if (
      Number.isFinite(descriptionBudgetMaxAttempts) &&
      descriptionBudgetMaxAttempts !== data.description_budget.max_attempts
    ) {
      payload.description_budget = { max_attempts: descriptionBudgetMaxAttempts };
    }
    if (values.recognitionEnabled !== data.recognition_enabled) {
      payload.recognition_enabled = values.recognitionEnabled;
    }
    if (
      typeof data.allow_person_names === 'boolean' &&
      values.allowPersonNames !== null &&
      values.allowPersonNames !== data.allow_person_names
    ) {
      payload.allow_person_names = values.allowPersonNames;
    }
    return payload;
  };

  const submitSnapshot = (
    values: SettingsFormSnapshot,
    data: SettingsResponse,
    queued = false,
  ): void => {
    const payload = buildSavePayload(values, data);
    if (Object.keys(payload).length === 0) {
      dispatch({
        type: 'setSaveMessage',
        message: __('No changes to save.', 'alt-context'),
        tone: 'warning',
      });
      return;
    }
    if (queued) {
      dispatch({ type: 'setSaveMessage', message: __('Saving…', 'alt-context'), tone: 'info' });
    }
    saveMutation.mutate(payload);
  };

  const drainQueuedSave = (refreshedSettings?: SettingsResponse): void => {
    const snapshot = queuedSaveSnapshot.current;
    if (!snapshot) {
      return;
    }
    queuedSaveSnapshot.current = null;
    const data = refreshedSettings
      ?? queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all)
      ?? settingsQuery.data;
    if (!data) {
      return;
    }
    routingSaveFeedback.current = false;
    routingSavePending.current = false;
    dispatch({ type: 'clearSaveMessage' });
    dispatch({ type: 'clearTestResult' });
    submitSnapshot(snapshot, data, true);
  };

  const saveMutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: async (data: SaveSettingsResponse) => {
      const isRoutingAutosave = routingSavePending.current;
      if (isRoutingAutosave) {
        routingSavePending.current = false;
        if (data.saved.some((field) => field === 'url' || field === 'api_key')) {
          healthProbeGeneration.current += 1;
        }
      }
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
        await queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
        const refreshedOnFail = await queryClient.fetchQuery({
          queryKey: queryKeys.settings.all,
          queryFn: fetchSettings,
        });
        syncLocalizedRouting(refreshedOnFail);
        drainQueuedSave(refreshedOnFail);
        return;
      }

      dispatch({
        type: 'setSaveMessage',
        message: isRoutingAutosave
          ? __('Saved — checking health…', 'alt-context')
          : __('Settings saved.', 'alt-context'),
        tone: isRoutingAutosave ? 'info' : 'success',
      });
      dispatch({ type: 'setApiKey', value: '' });
      await queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
      // A saved URL/key may repair the recognition breaker; refetch sync health
      // so the degraded/offline banner clears without waiting for its 15s poll.
      await queryClient.invalidateQueries({ queryKey: queryKeys.sync.health() });
      const refreshed = await queryClient.fetchQuery({
        queryKey: queryKeys.settings.all,
        queryFn: fetchSettings,
      });
      syncLocalizedRouting(refreshed);
      if (isRoutingAutosave) {
        startHealthCheck(true);
      }
      drainQueuedSave(refreshed);
    },
    onError: (error) => {
      const isRoutingAutosave = routingSavePending.current;
      if (isRoutingAutosave) {
        routingSavePending.current = false;
      }
      dispatch({
        type: 'setSaveMessage',
        message: resolveWpErrorMessage(error, __('Failed to save settings.', 'alt-context')),
        tone: 'error',
      });
      drainQueuedSave();
    },
  });

  const testMutation = useMutation({
    mutationFn: testConnection,
    // Keep mutation-level handlers for callers that invoke the captured hook
    // callbacks directly; real mutation results use the generation captured
    // by each call below.
    onSuccess: (data, variables?: Parameters<typeof testConnection>[0]) => {
      const metadata = variables && healthProbeMetadata.current.get(variables);
      const generation = metadata?.generation ?? healthProbeGeneration.current;
      applyHealthProbeSuccess(data, generation);
      if (generation === healthProbeGeneration.current && metadata?.afterRoutingSave) {
        clearRoutingCheckFeedback();
      }
    },
    // Outcome enum maps to fixed banner copy; it cannot carry a free-form server
    // message without a new enum member ([sr-007]). Leave NETWORK_ERROR as the
    // transport-failure stand-in — see REPORT.md.
    onError: (_error, variables?: Parameters<typeof testConnection>[0]) => {
      const metadata = variables && healthProbeMetadata.current.get(variables);
      const generation = metadata?.generation ?? healthProbeGeneration.current;
      applyHealthProbeError(generation);
      if (generation === healthProbeGeneration.current && metadata?.afterRoutingSave) {
        clearRoutingCheckFeedback();
      }
    },
  });

  const runHealthCheck = (
    variables: NonNullable<Parameters<typeof testConnection>[0]>,
    afterRoutingSave = false,
  ): void => {
    const generation = ++healthProbeGeneration.current;
    const probeVariables = { ...variables };
    healthProbeMetadata.current.set(probeVariables, { generation, afterRoutingSave });
    testMutation.mutate(probeVariables);
  };

  const startHealthCheck = (afterRoutingSave = false): void => {
    automaticHealthCheckStarted.current = true;
    dispatch({ type: 'clearTestResult' });
    runHealthCheck({}, afterRoutingSave);
  };

  useEffect(() => {
    if (
      settingsQuery.isLoading ||
      settingsQuery.isLoadingError ||
      !settingsQuery.data?.effective_target_url.trim() ||
      state.testResult ||
      automaticHealthCheckStarted.current
    ) {
      return;
    }
    startHealthCheck();
  }, [
    settingsQuery.data?.effective_target_url,
    settingsQuery.isLoading,
    settingsQuery.isLoadingError,
    state.testResult,
    startHealthCheck,
  ]);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (saveMutation.isPending) {
      queuedSaveSnapshot.current = captureFormSnapshot();
      dispatch({ type: 'setSaveMessage', message: __('Saving…', 'alt-context'), tone: 'info' });
      return;
    }
    routingSaveFeedback.current = false;
    routingSavePending.current = false;
    dispatch({ type: 'clearSaveMessage' });
    dispatch({ type: 'clearTestResult' });

    const data = settingsQuery.data;
    if (!data) {
      // Save is only reachable from the loaded form (render guards isLoading/
      // isError below); bail defensively so the diff never derefs undefined.
      return;
    }
    submitSnapshot(captureFormSnapshot(), data);
  };

  const commitRoutingFields = (checkIfUnchanged = false): void => {
    const data = settingsQuery.data;
    if (!data || saveMutation.isPending || routingSavePending.current) {
      return;
    }

    const payload: SaveSettingsPayload = {};
    if (state.url !== (data.url ?? '')) {
      payload.url = state.url;
    }
    if (state.apiKey) {
      payload.api_key = state.apiKey;
    }

    if (Object.keys(payload).length === 0) {
      if (checkIfUnchanged) {
        routingSaveFeedback.current = false;
        dispatch({ type: 'clearSaveMessage' });
        startHealthCheck();
      }
      return;
    }

    routingSavePending.current = true;
    routingSaveFeedback.current = true;
    dispatch({ type: 'clearTestResult' });
    dispatch({ type: 'setSaveMessage', message: __('Saving…', 'alt-context'), tone: 'info' });
    saveMutation.mutate(payload);
  };

  const handleTest = () => {
    commitRoutingFields(true);
  };

  const handleConfirmTenantPairing = () => {
    automaticHealthCheckStarted.current = true;
    runHealthCheck({ confirm_tenant_pairing: true });
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
          allowPersonNames: state.allowPersonNames,
          urlReadOnly,
          keyReadOnly,
        }}
        status={{
          savePending: saveMutation.isPending,
          testPending: testMutation.isPending,
          hasUnsavedRoutingChanges,
          testResult: state.testResult,
          saveMessage: state.saveMessage,
          saveMessageTone: state.saveMessageTone,
          routingSaveFeedback: routingSaveFeedback.current,
        }}
        actions={{
          onUrlChange: (value) => dispatch({ type: 'setUrl', value }),
          onApiKeyChange: (value) => dispatch({ type: 'setApiKey', value }),
          onDescriptionBudgetMaxAttemptsChange: (value) =>
            dispatch({ type: 'setDescriptionBudgetMaxAttempts', value }),
          onRecognitionEnabledChange: (value) => dispatch({ type: 'setRecognitionEnabled', value }),
          onAllowPersonNamesChange: (value) => dispatch({ type: 'setAllowPersonNames', value }),
          onSave: handleSave,
          onTest: handleTest,
          onCommitRouting: () => commitRoutingFields(),
          onFocusServiceUrl: () => {
            document.getElementById('acx-settings-url')?.focus();
          },
        }}
      />

      <GpuControlCard />

      {state.saveMessage && !routingSaveFeedback.current ? (
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

      <section id={SETTINGS_SECTION_RETENTION_ID} className="acx-settings__retention">
        <RetentionSection />
      </section>
    </section>
  );
};

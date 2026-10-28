import React, { useCallback, useEffect, useRef, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';

import {
  fetchSettings,
  saveSettings,
  testConnection,
  CONTEXT_CATEGORIES,
  effectiveContextCategories,
  SettingsSaveResult,
  TestConnectionOutcome,
  type SaveSettingsPayload,
  type SaveSettingsResponse,
  type ContextCategory,
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
import {
  useSettingsPageState,
  type NonRoutingField,
  type NonRoutingRevisions,
} from './settings/useSettingsPageState';
import {
  hasInsightFaceProof,
  matchesHealthProbeTarget,
  type HealthProbeBinding,
} from './settings/healthProbeProof';

const SETTINGS_SECTION_RETENTION_ID = 'acx-settings-section-retention';
const SETTINGS_SECTION_RETENTION_HEADING_ID = 'acx-retention-title';

interface SettingsFormSnapshot {
  url: string;
  urlRevision: number;
  apiKey: string;
  apiKeyRevision: number;
  nonRoutingRevisions: NonRoutingRevisions;
  descriptionBudgetMaxAttempts: string;
  recognitionEnabled: boolean;
  allowPersonNames: boolean | null;
  contextCategories: ContextCategory[];
}

type NonRoutingPayloadField = 'description_budget' | 'recognition_enabled' | 'allow_person_names' | 'context_categories';
// Each non-routing payload field and the form field whose edit revision it carries.
const NON_ROUTING_FIELDS: Record<NonRoutingPayloadField, NonRoutingField> = {
  description_budget: 'descriptionBudgetMaxAttempts',
  recognition_enabled: 'recognitionEnabled',
  allow_person_names: 'allowPersonNames',
  context_categories: 'contextCategories',
};
const NON_ROUTING_PAYLOAD_FIELDS = Object.keys(NON_ROUTING_FIELDS) as NonRoutingPayloadField[];

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
  const scheduledHealthCheck = useRef<{
    afterRoutingSave: boolean;
    request: object | null;
  } | null>({ afterRoutingSave: false, request: null });
  const healthProbeGeneration = useRef(0);
  const healthDeadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const healthProbeMetadata = useRef(new WeakMap<object, HealthProbeBinding & { afterRoutingSave: boolean }>());
  const currentHealthRequest = useRef<object | null>(null);
  const credentialRevision = useRef(Symbol());
  const routingSavePending = useRef(false);
  const hasAcknowledgedSave = useRef(false);
  const routingSaveFeedback = useRef(false);
  // Survives a failed routing save so Retry resends the whole failed scope.
  const routingSaveIncludesOtherSettings = useRef(false);
  const inFlightRoutingSnapshot = useRef<SettingsFormSnapshot | null>(null);
  const inFlightPayload = useRef<SaveSettingsPayload | null>(null);
  // Non-routing fields whose write failed and that no later write acknowledged.
  // Their failure and whole-form Retry outlive every unrelated routing save.
  const unsavedFields = useRef<NonRoutingPayloadField[]>([]);
  // Readback recovery is independent of an outstanding failed-field retry.
  const [settingsReloadWarning, setSettingsReloadWarning] = useState('');
  const inFlightUrlWrite = useRef(false);
  const urlReadbackAfter = useRef<number | null>(null);
  // A blur queues routing fields only; an explicit submit queues the full form.
  const queuedRoutingOnly = useRef(false);
  const queuedSaveSnapshot = useRef<SettingsFormSnapshot | null>(null);
  // An explicit check is intent even when the queued routing diff is empty.
  const queuedHealthCheck = useRef(false);
  const pendingNoopUrl = useRef<Pick<SettingsFormSnapshot, 'url' | 'urlRevision'> | null>(null);

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
  const resolvedSettings = useRef(settingsQuery.data);
  const observedQuery = useRef({
    data: settingsQuery.data,
    updatedAt: settingsQuery.dataUpdatedAt,
    fetching: settingsQuery.isFetching,
    error: settingsQuery.isError,
  });

  const invalidateHealthProbe = (preserveScheduledCheck = false): void => {
    if (preserveScheduledCheck && scheduledHealthCheck.current) {
      // Keep an unfinished automatic/post-save check queued for the published
      // Settings snapshot. Its old request still loses every proof binding.
      scheduledHealthCheck.current.request = null;
    } else {
      scheduledHealthCheck.current = null;
    }
    healthProbeGeneration.current += 1;
    credentialRevision.current = Symbol();
    currentHealthRequest.current = null;
    dispatch({ type: 'clearTestResult' });
  };

  // Invalidate during the settings transition, before a late mutation can run.
  // Refetches may keep identical data (including the same key last four).
  if (observedQuery.current.data !== settingsQuery.data
    || observedQuery.current.updatedAt !== settingsQuery.dataUpdatedAt
    || (!observedQuery.current.fetching && settingsQuery.isFetching)
    || observedQuery.current.error !== settingsQuery.isError) {
    observedQuery.current = {
      data: settingsQuery.data,
      updatedAt: settingsQuery.dataUpdatedAt,
      fetching: settingsQuery.isFetching,
      error: settingsQuery.isError,
    };
    resolvedSettings.current = settingsQuery.data;
    invalidateHealthProbe(true);
  } else {
    observedQuery.current.fetching = settingsQuery.isFetching;
  }

  useEffect(() => () => {
    if (healthDeadline.current !== null) clearTimeout(healthDeadline.current);
    healthProbeGeneration.current += 1;
    currentHealthRequest.current = null;
    scheduledHealthCheck.current = { afterRoutingSave: false, request: null };
  }, []);

  const isCurrentHealthProbe = (binding: HealthProbeBinding): boolean => {
    // Cache transitions can precede the hook's batched notification.
    const cachedQuery = queryClient.getQueryState?.<SettingsResponse>(queryKeys.settings.all);
    return binding.generation === healthProbeGeneration.current
      && binding.request === currentHealthRequest.current
      && binding.credentialRevision === credentialRevision.current
      && matchesHealthProbeTarget(binding, resolvedSettings.current)
      && !observedQuery.current.fetching && !observedQuery.current.error
      && (!cachedQuery || (
        cachedQuery.fetchStatus !== 'fetching'
        && cachedQuery.status !== 'error'
        && cachedQuery.data === observedQuery.current.data
        && cachedQuery.dataUpdatedAt === observedQuery.current.updatedAt
      ));
  };

  const syncLocalizedRouting = (settings: SettingsResponse): void => {
    if (!window.AltContextAdmin) {
      return;
    }

    window.AltContextAdmin.recognitionSource = settings.recognition_source;
    window.AltContextAdmin.effectiveTargetUrl = settings.effective_target_url;
    resetConfigCache();
  };

  const applyHealthProbeSuccess = (
    data: TestConnectionResponse,
    generation: number,
    proof?: HealthProbeBinding,
  ): void => {
    if (generation !== healthProbeGeneration.current) {
      return;
    }
    dispatch({ type: 'setTestResult', value: data, proof });
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

  // An unacknowledged failure outranks routing feedback: it stays beside the
  // service card, and Retry resends the whole form with the kept values.
  const showUnsavedFields = (): boolean => {
    if (unsavedFields.current.length === 0) {
      return false;
    }
    routingSaveFeedback.current = true;
    routingSaveIncludesOtherSettings.current = true;
    dispatch({
      type: 'setSaveMessage',
      message: sprintf(__('Could not save settings. (%s)', 'alt-context'), unsavedFields.current.join(', ')),
      tone: 'error',
    });
    return true;
  };

  const clearRoutingCheckFeedback = (): void => {
    if (routingSaveFeedback.current && !showUnsavedFields()) {
      routingSaveFeedback.current = false;
      dispatch({ type: 'clearSaveMessage' });
    }
  };

  const invalidateForRoutingEdit = (): void => {
    // An edit cancels an unfinished post-save check and its deadline. Settle the
    // "Checking health…" copy in the same transition; the card returns to draft.
    const cancelsPostSaveCheck = scheduledHealthCheck.current?.afterRoutingSave === true;
    queuedHealthCheck.current = false;
    invalidateHealthProbe();
    if (cancelsPostSaveCheck) {
      clearRoutingCheckFeedback();
    }
  };

  const captureFormSnapshot = (): SettingsFormSnapshot => ({
    url: state.url,
    urlRevision: state.urlRevision,
    apiKey: state.apiKey,
    apiKeyRevision: state.apiKeyRevision,
    nonRoutingRevisions: state.nonRoutingRevisions,
    descriptionBudgetMaxAttempts: state.descriptionBudgetMaxAttempts,
    recognitionEnabled: state.recognitionEnabled,
    allowPersonNames: state.allowPersonNames,
    contextCategories: [...state.contextCategories],
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
    const selectedContextCategories = CONTEXT_CATEGORIES.filter((category) =>
      values.contextCategories.includes(category),
    );
    const loadedContextCategories = effectiveContextCategories(data.context_categories);
    if (
      selectedContextCategories.length !== loadedContextCategories.length ||
      selectedContextCategories.some((category, index) => category !== loadedContextCategories[index])
    ) {
      payload.context_categories = selectedContextCategories;
    }
    return payload;
  };

  // The cached settings plus every field this write acknowledged. A failed
  // readback must never drain queued intent against values from before the write.
  const reconcileAcknowledged = (
    base: SettingsResponse,
    saved: string[],
    payload: SaveSettingsPayload | null,
  ): SettingsResponse => {
    const next = { ...base };
    if (!payload) {
      return next;
    }
    if (saved.includes('url') && payload.url !== undefined) {
      next.url = payload.url;
    }
    if (saved.includes('description_budget') && payload.description_budget) {
      next.description_budget = { ...base.description_budget, max_attempts: payload.description_budget.max_attempts };
    }
    if (saved.includes('recognition_enabled') && payload.recognition_enabled !== undefined) {
      next.recognition_enabled = payload.recognition_enabled;
    }
    if (saved.includes('allow_person_names') && payload.allow_person_names !== undefined) {
      next.allow_person_names = payload.allow_person_names;
    }
    if (saved.includes('context_categories') && payload.context_categories) {
      next.context_categories = payload.context_categories;
    }
    return next;
  };

  // Readbacks keep every unacknowledged non-routing edit (useSettingsPageState).
  // Only the revision a write carried becomes clean; a newer edit stays intent.
  const acknowledgeNonRouting = (values: SettingsFormSnapshot, fields: NonRoutingPayloadField[]): void => {
    if (fields.length === 0) {
      return;
    }
    const revisions: Partial<NonRoutingRevisions> = {};
    for (const field of fields) {
      revisions[NON_ROUTING_FIELDS[field]] = values.nonRoutingRevisions[NON_ROUTING_FIELDS[field]];
    }
    dispatch({ type: 'acknowledgeNonRouting', revisions });
    unsavedFields.current = unsavedFields.current.filter((field) => !fields.includes(field));
  };

  const recordUnsavedFields = (payload: SaveSettingsPayload | null, saved: string[]): void => {
    const failed = NON_ROUTING_PAYLOAD_FIELDS.filter((field) => payload?.[field] !== undefined && !saved.includes(field));
    unsavedFields.current = NON_ROUTING_PAYLOAD_FIELDS.filter(
      (field) => failed.includes(field) || unsavedFields.current.includes(field),
    );
  };

  const acknowledgeSatisfiedUrl = useCallback((data: SettingsResponse): void => {
    const committed = pendingNoopUrl.current;
    if (!committed || inFlightRoutingSnapshot.current || routingSavePending.current
      || queuedSaveSnapshot.current || settingsQuery.isFetching || settingsQuery.isError) {
      return;
    }
    // A retained cache value during refetch/error is not proof of completion.
    // Inspect the cache too: its transition can precede the hook notification.
    const cached = queryClient.getQueryState?.<SettingsResponse>(queryKeys.settings.all);
    if (cached && (cached.fetchStatus !== 'idle' || cached.status !== 'success'
      || cached.isInvalidated || cached.data !== data)) {
      return;
    }
    if (urlReadbackAfter.current !== null
      && (!cached || cached.dataUpdateCount <= urlReadbackAfter.current)) {
      return;
    }
    urlReadbackAfter.current = null;
    pendingNoopUrl.current = null;
    if (committed.url === (data.url ?? '')) {
      dispatch({ type: 'acknowledgeUrl', revision: committed.urlRevision });
    }
  }, [queryClient, settingsQuery.isFetching, settingsQuery.isError, dispatch]);

  const commitUrlNoop = (values: SettingsFormSnapshot, data: SettingsResponse): void => {
    // Only this committed revision can become clean, even if a newer draft
    // happens to have the same value. Pending writes must drain their intent first.
    pendingNoopUrl.current = values.url === (data.url ?? '')
      ? { url: values.url, urlRevision: values.urlRevision }
      : null;
    acknowledgeSatisfiedUrl(data);
  };

  const submitSnapshot = (
    values: SettingsFormSnapshot,
    data: SettingsResponse,
    queued = false,
    routingOnly = false,
  ): void => {
    commitUrlNoop(values, data);
    const payload: SaveSettingsPayload = routingOnly
      ? {
        ...(values.url !== data.url ? { url: values.url } : {}),
        ...(values.apiKey ? { api_key: values.apiKey } : {}),
      }
      : buildSavePayload(values, data);
    if (!routingOnly) {
      // A full-form write settles each non-routing field it omits: that value
      // already matches the settings it was diffed against.
      acknowledgeNonRouting(values, NON_ROUTING_PAYLOAD_FIELDS.filter((field) => payload[field] === undefined));
    }
    if (Object.keys(payload).length === 0) {
      // Draining satisfied intent is not a new save result. Keep the settled
      // feedback and retry scope, including a mixed save's partial failure.
      if (queued) return;
      dispatch({
        type: 'setSaveMessage',
        message: hasAcknowledgedSave.current ? __('All changes are saved.', 'alt-context') : __('No changes to save.', 'alt-context'),
        tone: hasAcknowledgedSave.current ? 'info' : 'warning',
      });
      return;
    }
    invalidateHealthProbe();
    if (queued || !routingOnly) {
      dispatch({ type: 'setSaveMessage', message: __('Saving…', 'alt-context'), tone: 'info' });
      const hasRoutingChanges = 'url' in payload || 'api_key' in payload;
      routingSavePending.current = hasRoutingChanges;
      routingSaveIncludesOtherSettings.current = hasRoutingChanges && Object.keys(payload).some(
        (field) => field !== 'url' && field !== 'api_key',
      );
      routingSaveFeedback.current = hasRoutingChanges;
    }
    inFlightRoutingSnapshot.current = values;
    inFlightPayload.current = payload;
    inFlightUrlWrite.current = 'url' in payload;
    saveMutation.mutate(payload);
  };

  const drainQueuedSave = (
    refreshedSettings?: SettingsResponse,
    readbackSucceeded = false,
  ): void => {
    const snapshot = queuedSaveSnapshot.current;
    if (snapshot) {
      queuedSaveSnapshot.current = null;
      const routingOnly = queuedRoutingOnly.current;
      queuedRoutingOnly.current = false;
      const data = refreshedSettings
        ?? queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all)
        ?? settingsQuery.data;
      if (!data) {
        return;
      }
      submitSnapshot(snapshot, data, true, routingOnly);
    }
    // Keep the request through further writes; an empty drain still completes
    // accepted health intent. Failed readback leaves it for Retry/Reload.
    if (readbackSucceeded && !inFlightRoutingSnapshot.current && queuedHealthCheck.current) {
      queuedHealthCheck.current = false;
      const showsUnsaved = showUnsavedFields();
      scheduledHealthCheck.current ??= { afterRoutingSave: !showsUnsaved, request: null };
      if (!showsUnsaved) {
        routingSaveFeedback.current = true;
        dispatch({ type: 'setSaveMessage', message: __('Saved. Checking health…', 'alt-context'), tone: 'info' });
      }
      startScheduledHealthCheck();
    }
  };

  // Readback failed after the server answered: publish the acknowledged fields
  // and return the snapshot that queued intent must be diffed against.
  const publishAcknowledged = (
    data: SaveSettingsResponse,
    settled: SettingsFormSnapshot | null,
    payload: SaveSettingsPayload | null,
  ): SettingsResponse | undefined => {
    const previous = queryClient.getQueryData<SettingsResponse>(queryKeys.settings.all);
    if (!previous || !settled || data.saved.length === 0) {
      return previous;
    }
    const reconciled = reconcileAcknowledged(previous, data.saved, payload);
    queryClient.setQueryData?.(queryKeys.settings.all, reconciled);
    return reconciled;
  };

  const saveMutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: async (data: SaveSettingsResponse) => {
      const settled = inFlightRoutingSnapshot.current;
      const payload = inFlightPayload.current;
      inFlightRoutingSnapshot.current = null;
      inFlightPayload.current = null;
      inFlightUrlWrite.current = false;
      if (settled && data.saved.includes('url')) {
        dispatch({ type: 'acknowledgeUrl', revision: settled.urlRevision });
      }
      if (settled && payload) {
        acknowledgeNonRouting(settled, NON_ROUTING_PAYLOAD_FIELDS.filter(
          (field) => payload[field] !== undefined && data.saved.includes(field),
        ));
      }
      if (settled?.apiKey && data.saved.includes('api_key')) {
        dispatch({ type: 'acknowledgeApiKey', value: settled.apiKey, revision: settled.apiKeyRevision });
        // Retire the acknowledged intent before readback can reject onSuccess
        // and React Query enters onError. Never retire a newer edit's intent.
        const queued = queuedSaveSnapshot.current;
        if (queued?.apiKeyRevision === settled.apiKeyRevision && queued.apiKey === settled.apiKey) {
          queuedSaveSnapshot.current = { ...queued, apiKey: '' };
        }
      }
      const isRoutingAutosave = routingSavePending.current;

      if (isRoutingAutosave) {
        routingSavePending.current = false;
        if (data.saved.some((field) => field === 'url' || field === 'api_key')) {
          invalidateHealthProbe();
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
          message: sprintf(__('Could not save settings. (%s)', 'alt-context'), failedFields),
          tone: 'error',
        });
        recordUnsavedFields(payload, data.saved);
        // Refresh so the form reflects what actually landed (partial success).
        try {
          await queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
          const refreshedOnFail = await queryClient.fetchQuery({
            queryKey: queryKeys.settings.all,
            queryFn: fetchSettings,
          });
          setSettingsReloadWarning('');
          syncLocalizedRouting(refreshedOnFail);
          drainQueuedSave(refreshedOnFail, true);
        } catch {
          // Keep the partial-write feedback, but never strand queued intent:
          // a stranded older key would later replay over a newer commit.
          drainQueuedSave(publishAcknowledged(data, settled, payload));
        }
        return;
      }

      hasAcknowledgedSave.current = true;
      // This write succeeded, but it did not acknowledge an earlier failed field.
      const showsUnsaved = showUnsavedFields();
      if (!showsUnsaved) {
        dispatch({
          type: 'setSaveMessage',
          message: isRoutingAutosave
            ? __('Saved. Checking health…', 'alt-context')
            : __('Settings saved.', 'alt-context'),
          tone: isRoutingAutosave ? 'info' : 'success',
        });
      }
      try {
        await queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
        // A saved URL/key may repair the recognition breaker; refetch sync health
        // so the degraded/offline banner clears without waiting for its 15s poll.
        await queryClient.invalidateQueries({ queryKey: queryKeys.sync.health() });
        const refreshed = await queryClient.fetchQuery({
          queryKey: queryKeys.settings.all,
          queryFn: fetchSettings,
        });
        setSettingsReloadWarning('');
        syncLocalizedRouting(refreshed);
        resolvedSettings.current = refreshed;
        if (isRoutingAutosave) {
          // The new target is still checked; with a failure kept in the card,
          // the result reports through the health banner instead.
          scheduledHealthCheck.current = { afterRoutingSave: !showsUnsaved, request: null };
          startScheduledHealthCheck();
        }
        drainQueuedSave(refreshed, true);
      } catch (error) {
        const reconciled = publishAcknowledged(data, settled, payload);
        scheduledHealthCheck.current = null;
        const warning = sprintf(__('Saved, but the page could not reload settings: %s.', 'alt-context'),
          resolveWpErrorMessage(error, __('settings unavailable', 'alt-context')));
        if (showUnsavedFields()) {
          setSettingsReloadWarning(warning);
        } else {
          setSettingsReloadWarning('');
          dispatch({ type: 'setSaveMessage', message: warning, tone: 'warning' });
        }
        drainQueuedSave(reconciled);
      }
    },
    onError: (error) => {
      if (inFlightUrlWrite.current) {
        // A rejected write can leave an idle cache from before that write.
        // Require a subsequent successful publication before proving a no-op.
        urlReadbackAfter.current = queryClient.getQueryState?.<SettingsResponse>(queryKeys.settings.all)?.dataUpdateCount
          ?? Infinity;
        inFlightUrlWrite.current = false;
      }
      recordUnsavedFields(inFlightPayload.current, []);
      inFlightRoutingSnapshot.current = null;
      inFlightPayload.current = null;
      const isRoutingAutosave = routingSavePending.current;
      if (isRoutingAutosave) {
        routingSavePending.current = false;
      }
      dispatch({
        type: 'setSaveMessage',
        message: isRoutingAutosave
          ? sprintf(__('Not saved: %s. Your edit is kept.', 'alt-context'),
            resolveWpErrorMessage(error, __('Failed to save settings', 'alt-context')))
          : resolveWpErrorMessage(error, __('Failed to save settings.', 'alt-context')),
        tone: 'error',
      });
      drainQueuedSave();
    },
  });

  useEffect(() => {
    if (!saveMutation.isPending && settingsQuery.data) {
      acknowledgeSatisfiedUrl(settingsQuery.data);
    }
  }, [
    saveMutation.isPending,
    settingsQuery.data,
    settingsQuery.dataUpdatedAt,
    settingsQuery.isFetching,
    settingsQuery.isError,
    acknowledgeSatisfiedUrl,
  ]);

  const testMutation = useMutation({
    mutationFn: testConnection,
    // Unbound legacy callbacks retain banner behavior, but cannot create proof.
    onSuccess: async (data, variables?: Parameters<typeof testConnection>[0]) => {
      const metadata = variables && healthProbeMetadata.current.get(variables);
      if (variables && (!metadata || !isCurrentHealthProbe(metadata))) {
        return;
      }
      scheduledHealthCheck.current = null;
      const generation = metadata?.generation ?? healthProbeGeneration.current;
      const tenantChanged = data.tenant_id !== undefined
        && data.tenant_id !== resolvedSettings.current?.tenant_id;
      applyHealthProbeSuccess(data, generation, tenantChanged ? undefined : metadata);
      if (generation === healthProbeGeneration.current && metadata?.afterRoutingSave) {
        clearRoutingCheckFeedback();
      }
      if (metadata && tenantChanged) {
        // Adoption can re-probe under another tenant inside the backend call.
        // Reconcile Settings first; only a subsequent bound check proves it.
        invalidateHealthProbe();
        await queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
        const refreshed = await queryClient.fetchQuery({
          queryKey: queryKeys.settings.all,
          queryFn: fetchSettings,
        });
        syncLocalizedRouting(refreshed);
        resolvedSettings.current = refreshed;
        scheduledHealthCheck.current = { afterRoutingSave: metadata.afterRoutingSave, request: null };
        startScheduledHealthCheck();
      }
    },
    // Outcome enum maps to fixed banner copy; it cannot carry a free-form server
    // message without a new enum member ([sr-007]). Leave NETWORK_ERROR as the
    // transport-failure stand-in — see REPORT.md.
    onError: (_error, variables?: Parameters<typeof testConnection>[0]) => {
      const metadata = variables && healthProbeMetadata.current.get(variables);
      if (variables && (!metadata || !isCurrentHealthProbe(metadata))) {
        return;
      }
      scheduledHealthCheck.current = null;
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
    scheduled = false,
  ): void => {
    dispatch({ type: 'clearTestResult' });
    const generation = ++healthProbeGeneration.current;
    const probeVariables = { ...variables };
    currentHealthRequest.current = probeVariables;
    if (scheduled && scheduledHealthCheck.current) {
      scheduledHealthCheck.current.request = probeVariables;
    } else {
      // Manual checks supersede pending scheduling rather than waiting on it.
      scheduledHealthCheck.current = null;
    }
    healthProbeMetadata.current.set(probeVariables, {
      generation,
      afterRoutingSave,
      request: probeVariables,
      endpoint: resolvedSettings.current?.effective_target_url ?? '',
      tenant: resolvedSettings.current?.tenant_id ?? '',
      credentialRevision: credentialRevision.current,
    });
    testMutation.mutate(probeVariables);
  };

  const startHealthCheck = (): void => {
    queuedHealthCheck.current = false;
    runHealthCheck({});
  };

  const startScheduledHealthCheck = (): void => {
    const scheduled = scheduledHealthCheck.current;
    if (
      !scheduled ||
      scheduled.request ||
      settingsQuery.isLoading ||
      settingsQuery.isLoadingError ||
      observedQuery.current.fetching ||
      observedQuery.current.error ||
      !resolvedSettings.current?.effective_target_url.trim()
    ) {
      return;
    }
    // fetchQuery can settle before the hook publishes its cached data/stamp.
    // Bind only after this render has observed the current settled snapshot.
    const cachedQuery = queryClient.getQueryState?.<SettingsResponse>(queryKeys.settings.all);
    if (cachedQuery && (
      cachedQuery.fetchStatus === 'fetching' ||
      cachedQuery.status === 'error' ||
      cachedQuery.data !== observedQuery.current.data ||
      cachedQuery.dataUpdatedAt !== observedQuery.current.updatedAt
    )) {
      return;
    }
    if (cachedQuery) {
      resolvedSettings.current = cachedQuery.data;
    }
    runHealthCheck({}, scheduled.afterRoutingSave, true);
  };

  useEffect(() => {
    startScheduledHealthCheck();
    if (scheduledHealthCheck.current && healthDeadline.current === null) {
      healthDeadline.current = setTimeout(() => {
        healthDeadline.current = null;
        const scheduled = scheduledHealthCheck.current;
        if (!scheduled) return;
        scheduledHealthCheck.current = null;
        currentHealthRequest.current = null;
        healthProbeGeneration.current += 1;
        if (scheduled.afterRoutingSave) {
          routingSaveFeedback.current = true;
          const reason = !resolvedSettings.current?.effective_target_url.trim()
            ? __('no service URL', 'alt-context')
            : observedQuery.current.error
              ? __('settings could not reload', 'alt-context')
              : __('health check timed out', 'alt-context');
          dispatch({ type: 'setSaveMessage',
            message: sprintf(__('Saved. Health not checked: %s.', 'alt-context'), reason),
            tone: 'warning' });
        }
      }, 15000);
    }
    if (!scheduledHealthCheck.current && healthDeadline.current !== null) {
      clearTimeout(healthDeadline.current);
      healthDeadline.current = null;
    }
  }, [
    settingsQuery.data,
    settingsQuery.dataUpdatedAt,
    settingsQuery.isFetching,
    settingsQuery.isError,
    settingsQuery.isLoading,
    settingsQuery.isLoadingError,
    startScheduledHealthCheck,
  ]);

  const submitForm = (): void => {
    invalidateHealthProbe();
    if (saveMutation.isPending) {
      queuedRoutingOnly.current = false;
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

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    submitForm();
  };

  const commitRoutingFields = (checkIfUnchanged = false): void => {
    const data = settingsQuery.data;
    if (!data) {
      return;
    }
    if (saveMutation.isPending || routingSavePending.current) {
      queuedHealthCheck.current ||= checkIfUnchanged;
      const committed = captureFormSnapshot();
      if (!queuedSaveSnapshot.current) {
        queuedRoutingOnly.current = true;
      }
      // A routing commit changes only routing intent in an already submitted form.
      queuedSaveSnapshot.current = queuedSaveSnapshot.current
        ? {
          ...queuedSaveSnapshot.current,
          url: committed.url,
          urlRevision: committed.urlRevision,
          apiKey: committed.apiKey,
          apiKeyRevision: committed.apiKeyRevision,
        }
        : committed;
      return;
    }

    commitUrlNoop(captureFormSnapshot(), data);
    const payload: SaveSettingsPayload = {};
    if (state.url !== (data.url ?? '')) {
      payload.url = state.url;
    }
    if (state.apiKey) {
      payload.api_key = state.apiKey;
    }

    if (Object.keys(payload).length === 0) {
      if (checkIfUnchanged) {
        if (!showUnsavedFields()) {
          routingSaveFeedback.current = false;
          dispatch({ type: 'clearSaveMessage' });
        }
        startHealthCheck();
      }
      return;
    }

    routingSavePending.current = true;
    routingSaveFeedback.current = true;
    routingSaveIncludesOtherSettings.current = false;
    inFlightRoutingSnapshot.current = captureFormSnapshot();
    inFlightPayload.current = payload;
    inFlightUrlWrite.current = 'url' in payload;
    invalidateHealthProbe();
    dispatch({ type: 'setSaveMessage', message: __('Saving…', 'alt-context'), tone: 'info' });
    saveMutation.mutate(payload);
  };

  const retryFailedSave = (): void => {
    // A failed mixed save is retried as the whole form, whose unacknowledged
    // non-routing values survived every readback. Autosave retries routing.
    if (routingSaveIncludesOtherSettings.current) {
      submitForm();
      return;
    }
    commitRoutingFields();
  };

  const handleTest = () => {
    commitRoutingFields(true);
  };

  const handleConfirmTenantPairing = () => {
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
            onClick={() => {
              invalidateHealthProbe(true);
              void settingsQuery.refetch();
            }}
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
  const hasUnsavedRoutingChanges = state.url !== data.url || state.apiKey !== '';
  const recognitionEngineVerified = !!state.testProof
    && isCurrentHealthProbe(state.testProof)
    && matchesHealthProbeTarget(state.testProof, data)
    && hasInsightFaceProof(state.testResult, state.testProof);
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
          contextCategories: state.contextCategories,
          urlReadOnly,
          keyReadOnly,
        }}
        status={{
          savePending: saveMutation.isPending,
          testPending: testMutation.isPending && currentHealthRequest.current !== null,
          hasUnsavedRoutingChanges,
          testResult: state.testResult,
          recognitionEngineVerified,
          saveMessage: state.saveMessage,
          saveMessageTone: state.saveMessageTone,
          routingSaveFeedback: routingSaveFeedback.current,
          settingsReloadWarning,
        }}
        actions={{
          onUrlChange: (value) => {
            invalidateForRoutingEdit();
            dispatch({ type: 'setUrl', value });
          },
          onApiKeyChange: (value) => {
            invalidateForRoutingEdit();
            dispatch({ type: 'setApiKey', value });
          },
          onDescriptionBudgetMaxAttemptsChange: (value) => {
            dispatch({ type: 'setDescriptionBudgetMaxAttempts', value });
          },
          onRecognitionEnabledChange: (value) => {
            dispatch({ type: 'setRecognitionEnabled', value });
          },
          onAllowPersonNamesChange: (value) => {
            dispatch({ type: 'setAllowPersonNames', value });
          },
          onContextCategoriesChange: (value) => {
            dispatch({ type: 'setContextCategories', value });
          },
          onSave: handleSave,
          onTest: handleTest,
          onCommitRouting: () => commitRoutingFields(),
          onRetrySave: retryFailedSave,
          onFocusServiceUrl: () => {
            document.getElementById('acx-settings-url')?.focus();
          },
        }}
        onRetryReload={() => {
          void settingsQuery.refetch().then((result) => {
            if (!result.isError) {
              setSettingsReloadWarning('');
              queuedHealthCheck.current = false;
              const showsUnsaved = showUnsavedFields();
              scheduledHealthCheck.current = { afterRoutingSave: !showsUnsaved, request: null };
              if (!showsUnsaved) {
                dispatch({ type: 'setSaveMessage',
                  message: __('Saved. Checking health…', 'alt-context'), tone: 'info' });
              }
            }
          });
        }}
        healthFeedback={state.testResult ? (
          <TestConnectionBannerView
            testResult={state.testResult}
            onConfirmTenantPairing={handleConfirmTenantPairing}
            confirmPending={testMutation.isPending}
          />
        ) : null}
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

      <section id={SETTINGS_SECTION_RETENTION_ID} className="acx-settings__retention">
        <RetentionSection />
      </section>
    </section>
  );
};

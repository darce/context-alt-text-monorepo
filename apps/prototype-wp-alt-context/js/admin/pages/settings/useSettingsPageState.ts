import { useEffect, useReducer } from 'react';

import {
  effectiveContextCategories,
  type ContextCategory,
  type SettingsResponse,
  type TestConnectionResponse,
} from '../../api/settingsApi';
import type { BannerTone } from './testConnectionBanner';
import type { HealthProbeBinding } from './healthProbeProof';

export type NonRoutingField =
  'descriptionBudgetMaxAttempts' | 'recognitionEnabled' | 'allowPersonNames' | 'contextCategories';
export type NonRoutingRevisions = Record<NonRoutingField, number>;

interface SettingsPageState {
  url: string;
  persistedUrl: string | null;
  urlRevision: number;
  acknowledgedUrlRevision: number;
  apiKey: string;
  apiKeyRevision: number;
  descriptionBudgetMaxAttempts: string;
  recognitionEnabled: boolean;
  allowPersonNames: boolean | null;
  contextCategories: ContextCategory[];
  // Each edit bumps its field's revision; a write acknowledges the revision it carried.
  nonRoutingRevisions: NonRoutingRevisions;
  acknowledgedNonRoutingRevisions: NonRoutingRevisions;
  saveMessage: string;
  saveMessageTone: BannerTone;
  testResult: TestConnectionResponse | null;
  testProof: HealthProbeBinding | null;
}

type SettingsPageAction =
  | { type: 'syncFromSettings'; settings: SettingsResponse }
  | { type: 'setUrl'; value: string }
  | { type: 'acknowledgeUrl'; revision: number }
  | { type: 'setApiKey'; value: string }
  | { type: 'acknowledgeApiKey'; value: string; revision: number }
  | { type: 'setDescriptionBudgetMaxAttempts'; value: string }
  | { type: 'setRecognitionEnabled'; value: boolean }
  | { type: 'setAllowPersonNames'; value: boolean }
  | { type: 'setContextCategories'; value: ContextCategory[] }
  | { type: 'acknowledgeNonRouting'; revisions: Partial<NonRoutingRevisions> }
  | { type: 'clearSaveMessage' }
  | { type: 'setSaveMessage'; message: string; tone: BannerTone }
  | { type: 'clearTestResult' }
  | { type: 'setTestResult'; value: TestConnectionResponse | null; proof?: HealthProbeBinding };

const NO_REVISIONS: NonRoutingRevisions = {
  descriptionBudgetMaxAttempts: 0,
  recognitionEnabled: 0,
  allowPersonNames: 0,
  contextCategories: 0,
};

const INITIAL_STATE: SettingsPageState = {
  url: '',
  persistedUrl: null,
  urlRevision: 0,
  acknowledgedUrlRevision: 0,
  apiKey: '',
  apiKeyRevision: 0,
  descriptionBudgetMaxAttempts: '-1',
  recognitionEnabled: true,
  allowPersonNames: null,
  contextCategories: effectiveContextCategories(null),
  nonRoutingRevisions: NO_REVISIONS,
  acknowledgedNonRoutingRevisions: NO_REVISIONS,
  saveMessage: '',
  saveMessageTone: 'success',
  testResult: null,
  testProof: null,
};

const edited = (state: SettingsPageState, field: NonRoutingField): NonRoutingRevisions => ({
  ...state.nonRoutingRevisions,
  [field]: state.nonRoutingRevisions[field] + 1,
});

const reducer = (state: SettingsPageState, action: SettingsPageAction): SettingsPageState => {
  switch (action.type) {
    case 'syncFromSettings': {
      // Readback updates persisted values without replacing an in-memory draft.
      // The write acknowledgement below is the only operation that clears a key.
      // A non-routing edit, pending or failed, likewise survives until acknowledged.
      const unacknowledged = (field: NonRoutingField): boolean =>
        state.nonRoutingRevisions[field] > state.acknowledgedNonRoutingRevisions[field];
      return {
        ...state,
        testResult: null,
        testProof: null,
        url: state.persistedUrl === null || state.urlRevision === state.acknowledgedUrlRevision
          ? action.settings.url
          : state.url,
        persistedUrl: action.settings.url,
        descriptionBudgetMaxAttempts: unacknowledged('descriptionBudgetMaxAttempts')
          ? state.descriptionBudgetMaxAttempts
          : String(action.settings.description_budget.max_attempts),
        recognitionEnabled: unacknowledged('recognitionEnabled')
          ? state.recognitionEnabled
          : action.settings.recognition_enabled,
        allowPersonNames: unacknowledged('allowPersonNames')
          ? state.allowPersonNames
          : action.settings.allow_person_names ?? null,
        contextCategories: unacknowledged('contextCategories')
          ? state.contextCategories
          : effectiveContextCategories(action.settings.context_categories),
      };
    }
    case 'setUrl':
      return { ...state, url: action.value, urlRevision: state.urlRevision + 1, testResult: null, testProof: null };
    case 'acknowledgeUrl':
      // Equality cannot distinguish an untouched URL from a newer deliberate revert.
      return { ...state, acknowledgedUrlRevision: Math.max(state.acknowledgedUrlRevision, action.revision) };
    case 'acknowledgeApiKey':
      return state.apiKeyRevision === action.revision && state.apiKey === action.value
        ? { ...state, apiKey: '' }
        : state;
    case 'setApiKey':
      return { ...state, apiKey: action.value, apiKeyRevision: state.apiKeyRevision + 1, testResult: null, testProof: null };
    case 'setDescriptionBudgetMaxAttempts':
      return {
        ...state,
        descriptionBudgetMaxAttempts: action.value,
        nonRoutingRevisions: edited(state, 'descriptionBudgetMaxAttempts'),
      };
    case 'setRecognitionEnabled':
      return { ...state, recognitionEnabled: action.value, nonRoutingRevisions: edited(state, 'recognitionEnabled') };
    case 'setAllowPersonNames':
      return { ...state, allowPersonNames: action.value, nonRoutingRevisions: edited(state, 'allowPersonNames') };
    case 'setContextCategories':
      return { ...state, contextCategories: action.value, nonRoutingRevisions: edited(state, 'contextCategories') };
    case 'acknowledgeNonRouting': {
      // An older write's acknowledgement never cleans a newer edit of the same field.
      const acknowledged = { ...state.acknowledgedNonRoutingRevisions };
      for (const field of Object.keys(action.revisions) as NonRoutingField[]) {
        acknowledged[field] = state.nonRoutingRevisions[field];
      }
      return { ...state, acknowledgedNonRoutingRevisions: acknowledged };
    }
    case 'clearSaveMessage':
      return { ...state, saveMessage: '', saveMessageTone: 'success' };
    case 'setSaveMessage':
      return { ...state, saveMessage: action.message, saveMessageTone: action.tone };
    case 'clearTestResult':
      return { ...state, testResult: null, testProof: null };
    case 'setTestResult':
      return { ...state, testResult: action.value, testProof: action.proof ?? null };
    default:
      return state;
  }
};

export const useSettingsPageState = (settings: SettingsResponse | undefined) => {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  useEffect(() => {
    if (settings) {
      dispatch({ type: 'syncFromSettings', settings });
    }
  }, [settings]);

  return { state, dispatch };
};

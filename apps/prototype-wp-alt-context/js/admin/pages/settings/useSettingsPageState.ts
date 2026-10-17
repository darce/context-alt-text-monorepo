import { useEffect, useReducer } from 'react';

import {
  effectiveContextCategories,
  type ContextCategory,
  type SettingsResponse,
  type TestConnectionResponse,
} from '../../api/settingsApi';
import type { BannerTone } from './testConnectionBanner';
import type { HealthProbeBinding } from './healthProbeProof';

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
  | { type: 'clearSaveMessage' }
  | { type: 'setSaveMessage'; message: string; tone: BannerTone }
  | { type: 'clearTestResult' }
  | { type: 'setTestResult'; value: TestConnectionResponse | null; proof?: HealthProbeBinding };

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
  saveMessage: '',
  saveMessageTone: 'success',
  testResult: null,
  testProof: null,
};

const reducer = (state: SettingsPageState, action: SettingsPageAction): SettingsPageState => {
  switch (action.type) {
    case 'syncFromSettings':
      // Readback updates persisted values without replacing an in-memory draft.
      // The write acknowledgement below is the only operation that clears a key.
      return {
        ...state,
        testResult: null,
        testProof: null,
        url: state.persistedUrl === null || state.urlRevision === state.acknowledgedUrlRevision
          ? action.settings.url
          : state.url,
        persistedUrl: action.settings.url,
        descriptionBudgetMaxAttempts: String(action.settings.description_budget.max_attempts),
        recognitionEnabled: action.settings.recognition_enabled,
        allowPersonNames: action.settings.allow_person_names ?? null,
        contextCategories: effectiveContextCategories(action.settings.context_categories),
      };
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
      return { ...state, descriptionBudgetMaxAttempts: action.value };
    case 'setRecognitionEnabled':
      return { ...state, recognitionEnabled: action.value };
    case 'setAllowPersonNames':
      return { ...state, allowPersonNames: action.value };
    case 'setContextCategories':
      return { ...state, contextCategories: action.value };
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

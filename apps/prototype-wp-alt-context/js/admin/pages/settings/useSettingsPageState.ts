import { useEffect, useReducer } from 'react';

import type { SettingsResponse, TestConnectionResponse } from '../../api/settingsApi';
import type { BannerTone } from './testConnectionBanner';

interface SettingsPageState {
  url: string;
  apiKey: string;
  descriptionBudgetMaxAttempts: string;
  saveMessage: string;
  saveMessageTone: BannerTone;
  testResult: TestConnectionResponse | null;
}

type SettingsPageAction =
  | { type: 'syncFromSettings'; settings: SettingsResponse }
  | { type: 'setUrl'; value: string }
  | { type: 'setApiKey'; value: string }
  | { type: 'setDescriptionBudgetMaxAttempts'; value: string }
  | { type: 'clearSaveMessage' }
  | { type: 'setSaveMessage'; message: string; tone: BannerTone }
  | { type: 'clearTestResult' }
  | { type: 'setTestResult'; value: TestConnectionResponse | null };

const INITIAL_STATE: SettingsPageState = {
  url: '',
  apiKey: '',
  descriptionBudgetMaxAttempts: '-1',
  saveMessage: '',
  saveMessageTone: 'success',
  testResult: null,
};

const reducer = (state: SettingsPageState, action: SettingsPageAction): SettingsPageState => {
  switch (action.type) {
    case 'syncFromSettings':
      return {
        ...state,
        url: action.settings.url,
        apiKey: '',
        descriptionBudgetMaxAttempts: String(action.settings.description_budget.max_attempts),
      };
    case 'setUrl':
      return { ...state, url: action.value };
    case 'setApiKey':
      return { ...state, apiKey: action.value };
    case 'setDescriptionBudgetMaxAttempts':
      return { ...state, descriptionBudgetMaxAttempts: action.value };
    case 'clearSaveMessage':
      return { ...state, saveMessage: '', saveMessageTone: 'success' };
    case 'setSaveMessage':
      return { ...state, saveMessage: action.message, saveMessageTone: action.tone };
    case 'clearTestResult':
      return { ...state, testResult: null };
    case 'setTestResult':
      return { ...state, testResult: action.value };
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

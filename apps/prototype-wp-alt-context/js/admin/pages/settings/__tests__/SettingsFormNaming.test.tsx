import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SettingsForm } from '../SettingsForm';
import type { SettingsResponse } from '../../../api/settingsApi';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string) => text,
}));

const settings = (allowPersonNames: boolean | null, error: string | null = null): SettingsResponse => ({
  url: 'https://api.example.com',
  url_source: 'option',
  url_rejection_reason: null,
  url_rejection_source: null,
  url_rejection_value: null,
  effective_target_url: 'https://api.example.com',
  effective_target_mode: 'service',
  recognition_source: 'service',
  recognition_source_source: 'option',
  api_key_set: true,
  api_key_last4: '****abcd',
  key_source: 'option',
  tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  tenant_id_source: 'option',
  tenant_paired: true,
  alt_style: 'alt_only',
  recognition_enabled: true,
  allow_person_names: allowPersonNames,
  allow_person_names_error: error,
  description_budget: {
    max_attempts: -1,
    usage: { attempts: 0, successes: 0, failures: 0, cost_total: 0 },
    recent_errors: [],
  },
});

const renderForm = (data: SettingsResponse, onAllowPersonNamesChange = vi.fn()) =>
  render(
    <SettingsForm
      values={{
        data,
        url: data.url,
        apiKey: '',
        descriptionBudgetMaxAttempts: String(data.description_budget.max_attempts),
        recognitionEnabled: data.recognition_enabled,
        allowPersonNames: data.allow_person_names,
        urlReadOnly: false,
        keyReadOnly: false,
      }}
      status={{
        savePending: false,
        testPending: false,
        hasUnsavedRoutingChanges: false,
        testResult: null,
      }}
      actions={{
        onUrlChange: vi.fn(),
        onApiKeyChange: vi.fn(),
        onDescriptionBudgetMaxAttemptsChange: vi.fn(),
        onRecognitionEnabledChange: vi.fn(),
        onAllowPersonNamesChange,
        onSave: vi.fn(),
        onTest: vi.fn(),
      }}
    />,
  );

describe('SettingsForm naming agreement toggle', () => {
  it('renders the service-owned flag and sends changes to the parent state', () => {
    const onChange = vi.fn();
    renderForm(settings(true), onChange);

    const toggle = screen.getByRole('checkbox', { name: 'Include named people in descriptions' });
    expect(toggle).toBeChecked();
    expect(screen.getByText('Names come from the People roster and are applied only when recognition is enabled.'))
      .toBeInTheDocument();

    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it('disables the toggle and surfaces the service error when the authority is unknown', () => {
    renderForm(settings(null, 'Recognition service unavailable.'));

    const toggle = screen.getByRole('checkbox', { name: 'Include named people in descriptions' });
    expect(toggle).toBeDisabled();
    expect(screen.getByTestId('acx-settings-allow-person-names-error'))
      .toHaveTextContent('Recognition service unavailable.');
  });
});


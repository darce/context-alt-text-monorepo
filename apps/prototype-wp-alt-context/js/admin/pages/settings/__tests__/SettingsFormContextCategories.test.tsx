import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  CONTEXT_CATEGORIES,
  effectiveContextCategories,
  type ContextCategory,
  type SettingsResponse,
} from '../../../api/settingsApi';
import { SettingsForm } from '../SettingsForm';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string) => text,
}));

const settings = (
  contextCategories: ContextCategory[] | null,
  error: string | null = null,
): SettingsResponse => ({
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
  allow_person_names: true,
  allow_person_names_error: null,
  context_categories: contextCategories,
  context_categories_error: error,
  description_budget: {
    max_attempts: -1,
    usage: { attempts: 0, successes: 0, failures: 0, cost_total: 0 },
    recent_errors: [],
  },
});

const renderForm = (data: SettingsResponse, onChange = vi.fn()) =>
  render(
    <SettingsForm
      values={{
        data,
        url: data.url,
        apiKey: '',
        descriptionBudgetMaxAttempts: String(data.description_budget.max_attempts),
        recognitionEnabled: data.recognition_enabled,
        allowPersonNames: data.allow_person_names,
        contextCategories: effectiveContextCategories(data.context_categories),
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
        onAllowPersonNamesChange: vi.fn(),
        onContextCategoriesChange: onChange,
        onSave: vi.fn(),
        onTest: vi.fn(),
      }}
    />,
  );

describe('SettingsForm context categories', () => {
  it('checks all categories when GET returns null', () => {
    renderForm(settings(null));

    for (const label of ['Attachment details', 'Parent post', 'Categories and tags', 'Product name']) {
      expect(screen.getByRole('checkbox', { name: label })).toBeChecked();
    }
    expect(screen.getByRole('group', { name: 'Site context sent with each image' })).toBeInTheDocument();
    expect(screen.getByText("The image itself is always sent. People's names follow the naming setting above."))
      .toBeInTheDocument();
  });

  it('checks only the stored subset', () => {
    renderForm(settings(['attachment', 'product']));

    expect(screen.getByRole('checkbox', { name: 'Attachment details' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Parent post' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Categories and tags' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Product name' })).toBeChecked();
  });

  it('checks none when GET returns an empty array', () => {
    renderForm(settings([]));

    for (const label of ['Attachment details', 'Parent post', 'Categories and tags', 'Product name']) {
      expect(screen.getByRole('checkbox', { name: label })).not.toBeChecked();
    }
  });

  it('renders the context category error as an alert', () => {
    renderForm(settings(['attachment'], 'Stored context categories are malformed.'));

    expect(screen.getByTestId('acx-settings-context-categories-error')).toHaveAttribute('role', 'alert');
    expect(screen.getByTestId('acx-settings-context-categories-error'))
      .toHaveTextContent('Stored context categories are malformed.');
  });

  it('ignores unknown category names and keeps the canonical category order', () => {
    expect(effectiveContextCategories(['product', 'unknown', 'post'])).toEqual([
      CONTEXT_CATEGORIES[1],
      CONTEXT_CATEGORIES[3],
    ]);
  });
});

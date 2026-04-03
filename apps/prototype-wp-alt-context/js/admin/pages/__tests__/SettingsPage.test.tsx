import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { SettingsPage } from '../SettingsPage';
import type { SettingsResponse } from '../../api/settingsApi';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';

type QueryHookResult = ReturnType<typeof createMockQuery<SettingsResponse>>;
type MutationHookResult = ReturnType<typeof createMockMutation>;

const { mockUseQuery, mockUseMutation } = vi.hoisted(() => ({
  mockUseQuery: vi.fn<() => QueryHookResult>(),
  mockUseMutation: vi.fn<() => MutationHookResult>(),
}));

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../api/settingsApi', () => ({
  fetchSettings: vi.fn(),
  saveSettings: vi.fn(),
  testConnection: vi.fn(),
}));

vi.mock('../../api/config', () => ({
  getEndpoint: (key: string) => `/acx/v1/${key}`,
  getConfig: () => ({
    nonce: 'test-nonce',
    endpoints: { settings: '/acx/v1/settings', settingsTest: '/acx/v1/settings/test' },
  }),
}));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    useQuery: mockUseQuery,
    useMutation: mockUseMutation,
  };
});

const defaultSettings: SettingsResponse = {
  url: 'https://api.example.com',
  url_source: 'option',
  api_key_set: true,
  api_key_last4: '****abcd',
  key_source: 'option',
};

describe('SettingsPage', () => {
  const saveMutate = vi.fn();
  const testMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();

    // useMutation is called twice: first for save, then for test connection.
    let mutationCallIndex = 0;
    mockUseMutation.mockImplementation(() => {
      mutationCallIndex++;
      if (mutationCallIndex % 2 === 1) {
        return createMockMutation({ mutate: saveMutate });
      }
      return createMockMutation({ mutate: testMutate });
    });
  });

  it('shows loading state initially', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ status: 'pending' }));
    render(<SettingsPage />);
    expect(screen.getByText('Loading settings…')).toBeInTheDocument();
  });

  it('shows error state when settings fail to load', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ isError: true, error: new Error('fail') }));
    render(<SettingsPage />);
    expect(screen.getByText('Failed to load settings.')).toBeInTheDocument();
  });

  it('renders the settings form with loaded data', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    expect(screen.getByLabelText('API URL')).toHaveValue('https://api.example.com');
    expect(screen.getAllByText('Saved in database')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Test Connection' })).toBeEnabled();
  });

  it('saves settings when the form is submitted with changes', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.change(screen.getByLabelText('API URL'), {
      target: { value: 'https://new-api.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(saveMutate).toHaveBeenCalledWith({ url: 'https://new-api.example.com' });
  });

  it('shows "no changes" when submitting without modifications', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Save Settings' }));

    expect(screen.getByText('No changes to save.')).toBeInTheDocument();
    expect(saveMutate).not.toHaveBeenCalled();
  });

  it('tests connection and invokes the test mutation', () => {
    mockUseQuery.mockReturnValue(createMockQuery({ data: defaultSettings }));
    render(<SettingsPage />);

    fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }));

    expect(testMutate).toHaveBeenCalled();
  });

  it('renders read-only fields when source is constant', () => {
    mockUseQuery.mockReturnValue(
      createMockQuery({
        data: { ...defaultSettings, url_source: 'constant' as const, key_source: 'constant' as const },
      }),
    );
    render(<SettingsPage />);

    expect(screen.getByLabelText('API URL')).toHaveAttribute('readOnly');
    expect(screen.getByLabelText('API Key')).toHaveAttribute('readOnly');
    expect(screen.getByRole('button', { name: 'Save Settings' })).toBeDisabled();
  });
});

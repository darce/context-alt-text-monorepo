import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { registerConfig, resetConfigCache } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import { fetchSettings, saveSettings, type SettingsResponse } from '../../../api/settingsApi';
import { RecognitionPolicyControl } from '../RecognitionPolicyControl';
vi.mock('../../../api/settingsApi', () => ({ fetchSettings: vi.fn(), saveSettings: vi.fn() }));
const settings = (enabled: unknown) => ({ recognition_enabled: enabled, url: 'https://service.example', api_key_set: true }) as SettingsResponse;
let client: QueryClient;
const boot = (policy: unknown = { enabled: false, canManage: true }) => registerConfig({ nonce: 'abcdef1234', ajaxUrl: '/ajax', endpoints: {}, recognitionPolicy: policy });
const mount = () => render(<QueryClientProvider client={client}><RecognitionPolicyControl /></QueryClientProvider>);
beforeEach(() => {
  vi.resetAllMocks(); resetConfigCache(); boot();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(fetchSettings).mockResolvedValue(settings(false));
  vi.mocked(saveSettings).mockResolvedValue({ result: 'ok', saved: ['recognition_enabled'] });
});
afterEach(() => { cleanup(); client.clear(); resetConfigCache(); });
it.each([false, true])('persists from %s using only policy, keyboard, readback and shared cache/remount', async (initial) => {
  vi.mocked(fetchSettings).mockResolvedValueOnce(settings(initial)).mockResolvedValue(settings(!initial));
  const view = mount(); const user = userEvent.setup();
  const button = await screen.findByRole('button', { name: initial ? 'Disable facial recognition' : 'Enable facial recognition' });
  await waitFor(() => expect(button).toBeEnabled()); button.focus(); await user.keyboard('{Enter}');
  await screen.findByText('Policy saved and verified.');
  expect(saveSettings).toHaveBeenCalledExactlyOnceWith({ recognition_enabled: !initial });
  expect(client.getQueryData<SettingsResponse>(queryKeys.settings.all)?.recognition_enabled).toBe(!initial);
  view.unmount(); mount(); await screen.findByRole('button', { name: initial ? 'Enable facial recognition' : 'Disable facial recognition' });
});
it.each([false, undefined, 'true'])('does not read sensitive settings for capability %s', async (cap) => {
  boot({ enabled: true, canManage: cap }); mount();
  expect(screen.getByText(/administrator/i)).toBeInTheDocument();
  expect(fetchSettings).not.toHaveBeenCalled(); expect(saveSettings).not.toHaveBeenCalled();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it.each([{}, { recognition_enabled: 'false' }, { recognition_enabled: null }])('rejects malformed live settings %j', async (data) => {
  vi.mocked(fetchSettings).mockResolvedValue(data as SettingsResponse); mount();
  await screen.findByRole('button', { name: 'Retry reading policy' });
  expect(screen.queryByRole('button', { name: 'Enable facial recognition' })).not.toBeInTheDocument();
});
it.each([{ result: 'error', saved: [], failed: ['recognition_enabled'] }, { result: 'partial', saved: ['url'], failed: ['recognition_enabled'] }, { result: 'ok', saved: [] }])('rejects HTTP200 field failure %j', async (response) => {
  vi.mocked(saveSettings).mockResolvedValue(response as Awaited<ReturnType<typeof saveSettings>>); mount();
  await userEvent.click(await screen.findByRole('button', { name: 'Enable facial recognition' }));
  await screen.findByRole('button', { name: 'Retry reading policy' });
  expect(screen.queryByText('Policy saved and verified.')).not.toBeInTheDocument();
});
it.each(['reject', 'mismatch'])('retries only reads after acknowledged write and %s', async (mode) => {
  vi.mocked(fetchSettings).mockResolvedValueOnce(settings(false));
  if (mode === 'reject') vi.mocked(fetchSettings).mockRejectedValueOnce(new Error('offline'));
  else vi.mocked(fetchSettings).mockResolvedValueOnce(settings(false));
  vi.mocked(fetchSettings).mockResolvedValue(settings(true)); mount();
  await userEvent.click(await screen.findByRole('button', { name: 'Enable facial recognition' }));
  await userEvent.click(await screen.findByRole('button', { name: 'Retry reading policy' }));
  await screen.findByText('Policy saved and verified.'); expect(saveSettings).toHaveBeenCalledTimes(1);
});
it('keeps actions disabled while save is pending', async () => {
  vi.mocked(saveSettings).mockReturnValue(new Promise(() => {})); mount();
  await userEvent.click(await screen.findByRole('button', { name: 'Enable facial recognition' }));
  expect(screen.getByRole('button', { name: /Saving/ })).toBeDisabled();
});
it('handles transport failure with read recovery', async () => {
  vi.mocked(saveSettings).mockRejectedValue(new Error('offline')); mount();
  await userEvent.click(await screen.findByRole('button', { name: 'Enable facial recognition' }));
  await screen.findByRole('button', { name: 'Retry reading policy' });
});
it('stops further settings access after permission loss', async () => {
  const { HTTPError } = await import('../../../utils/http');
  vi.mocked(saveSettings).mockRejectedValue(new HTTPError({ status: 403, retryAfterSeconds: undefined, endpoint: '/settings', bodyPreview: '', message: 'Forbidden' }));
  mount();
  await userEvent.click(await screen.findByRole('button', { name: 'Enable facial recognition' }));
  await screen.findByText(/administrator/i);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(fetchSettings).toHaveBeenCalledTimes(1);
});

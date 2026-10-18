import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PortalKeyClient, PortalKeyMetadataResponse, PortalKeyPageResponse } from '../api/portalKeys';
import { KeysScreen } from '../screens/KeysScreen';

const TENANT_A = '11111111-1111-4111-8111-111111111111';
const KEY_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

function metadata(): PortalKeyMetadataResponse {
  return {
    id: KEY_A,
    tenant_id: TENANT_A,
    created_at: '2026-09-01T00:00:00Z',
    expires_at: '2026-12-01T00:00:00Z',
    revoked_at: null,
    rate_limit_tier: 'standard',
    lifetime_seconds: 3600,
  };
}

function page(): PortalKeyPageResponse {
  return { data: [metadata()], next_cursor: null, cursor: null, limit: 25, total: 1 };
}

function keyError(): Error & { status: number; code: string; detail: string } {
  return Object.assign(new Error('portal_key_request_failed'), {
    status: 409,
    code: 'last_usable_key_confirmation_required',
    detail: 'last_usable_key_confirmation_required',
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderKeys(client: PortalKeyClient) {
  return render(
    <KeysScreen
      client={client}
      sessionKey="sess-a"
      onNavigateToUsage={vi.fn()}
      onNavigateToBilling={vi.fn()}
      onOpenWordPressGuidance={vi.fn()}
    />,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ADVFIX-1 PMONEY-M-3 revoke dialog pending state', () => {
  it('keeps the last-usable confirmation open while its revoke is pending', async () => {
    const user = userEvent.setup();
    const response = deferred<Awaited<ReturnType<PortalKeyClient['revoke']>>>();
    const revoke = vi.fn<PortalKeyClient['revoke']>()
      .mockRejectedValueOnce(keyError())
      .mockImplementationOnce(() => response.promise);
    renderKeys({
      list: vi.fn(async () => page()),
      create: vi.fn(),
      rotate: vi.fn(),
      revoke,
    });

    await waitFor(() => expect(screen.getByRole('button', { name: /revoke key/i })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: /revoke key/i }));
    await user.click(screen.getByRole('button', { name: /confirm revoke/i }));
    const dialog = await screen.findByRole('dialog', { name: /last usable key/i });
    await user.click(within(dialog).getByRole('button', { name: /confirm revoke/i }));
    await waitFor(() => expect(revoke).toHaveBeenCalledTimes(2));

    expect(within(dialog).getByRole('button', { name: /keep key/i })).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: /revoking/i })).toBeDisabled();
    expect(within(dialog).getByText(/revoking api key/i)).toBeInTheDocument();
    expect(dialog).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: /last usable key/i })).toBeInTheDocument();

    response.resolve({ id: KEY_A, tenant_id: TENANT_A, revoked: true });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(revoke.mock.calls[1]?.[1]).toEqual({ confirm_last_usable: true });
  });

  it('does not dismiss an in-flight preview or reopen it from a late confirmation warning', async () => {
    const user = userEvent.setup();
    const response = deferred<Awaited<ReturnType<PortalKeyClient['revoke']>>>();
    const revoke = vi.fn<PortalKeyClient['revoke']>(() => response.promise);
    renderKeys({
      list: vi.fn(async () => page()),
      create: vi.fn(),
      rotate: vi.fn(),
      revoke,
    });

    await waitFor(() => expect(screen.getByRole('button', { name: /revoke key/i })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: /revoke key/i }));
    const preview = screen.getByRole('dialog', { name: /revoke api key/i });
    await user.click(within(preview).getByRole('button', { name: /confirm revoke/i }));
    await waitFor(() => expect(revoke).toHaveBeenCalledTimes(1));

    expect(within(preview).getByRole('button', { name: /keep key/i })).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', { name: /revoke api key/i })).toBeInTheDocument();

    response.reject(keyError());
    expect(await screen.findByRole('dialog', { name: /last usable key/i })).toBeInTheDocument();
    expect(revoke.mock.calls[0]?.[1]).toEqual({});
  });
});

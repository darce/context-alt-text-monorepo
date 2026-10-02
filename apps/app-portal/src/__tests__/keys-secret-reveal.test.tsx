import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { createPortalKeyClient, type PortalKeyMetadataResponse, type PortalKeyPageResponse } from '../api/portalKeys';
import { KeysScreen } from '../screens/KeysScreen';

const TENANT_ID = '11111111-1111-4111-8111-111111111111';
const KEY_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const KEY_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const CREATED_SECRET = 'acx_live_created_secret_once';
const ROTATED_SECRET = 'acx_live_rotated_secret_once';
const REPLAYED_SECRET = 'acx_live_replayed_secret_unavailable';

type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function metadata(id = KEY_A): PortalKeyMetadataResponse {
  return {
    id,
    tenant_id: TENANT_ID,
    created_at: '2026-09-01T00:00:00Z',
    expires_at: '2026-12-01T00:00:00Z',
    revoked_at: null,
    rate_limit_tier: 'standard',
    lifetime_seconds: 3600,
  };
}

function page(rows: PortalKeyMetadataResponse[]): PortalKeyPageResponse {
  return {
    data: rows,
    next_cursor: null,
    cursor: null,
    limit: 25,
    total: rows.length,
  };
}

function issue(id: string, rawKey: string | null, replayed = false) {
  return { ...metadata(id), raw_key: rawKey, replayed };
}

function requestForIssue(responseBody: unknown, rows: PortalKeyMetadataResponse[] = []) {
  return vi.fn<PortalRequest>(async (_path, init) =>
    init?.method === 'POST' ? jsonResponse(200, responseBody) : jsonResponse(200, page(rows)),
  );
}

function renderKeys(request: PortalRequest) {
  return render(
    <KeysScreen
      client={createPortalKeyClient(request)}
      sessionKey="session-a"
      onNavigateToUsage={vi.fn()}
      onNavigateToBilling={vi.fn()}
      onOpenWordPressGuidance={vi.fn()}
    />,
  );
}

describe('KeysScreen fresh secret reveal through the real key client', () => {
  it('shows a fresh create secret with copy, then removes it when the dialog closes', async () => {
    const user = userEvent.setup();
    const request = requestForIssue(issue(KEY_A, CREATED_SECRET));
    renderKeys(request);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));

    const dialog = await screen.findByRole('dialog', { name: /copy this api secret once/i });
    expect(within(dialog).getByText(CREATED_SECRET)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /copy secret/i })).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('/portal/keys', expect.objectContaining({ method: 'POST' }));

    await user.click(within(dialog).getByRole('button', { name: /close secret/i }));
    expect(screen.queryByText(CREATED_SECRET)).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: /copy this api secret once/i })).not.toBeInTheDocument();
  });

  it('shows a fresh rotate secret with copy through the real key client', async () => {
    const user = userEvent.setup();
    const request = requestForIssue(issue(KEY_B, ROTATED_SECRET), [metadata(KEY_A)]);
    renderKeys(request);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /rotate key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /rotate key/i }));

    const dialog = await screen.findByRole('dialog', { name: /copy this api secret once/i });
    expect(within(dialog).getByText(ROTATED_SECRET)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /copy secret/i })).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith(`/portal/keys/${KEY_A}/rotate`, expect.objectContaining({ method: 'POST' }));

    await user.click(within(dialog).getByRole('button', { name: /close secret/i }));
    expect(screen.queryByText(ROTATED_SECRET)).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: /copy this api secret once/i })).not.toBeInTheDocument();
  });

  it('does not show a replayed response secret or offer copy', async () => {
    const user = userEvent.setup();
    const request = requestForIssue(issue(KEY_A, REPLAYED_SECRET, true));
    renderKeys(request);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create api key/i })).toBeEnabled();
    });
    await user.click(screen.getByRole('button', { name: /create api key/i }));

    const dialog = await screen.findByRole('dialog', { name: /copy this api secret once/i });
    expect(within(dialog).getByText(/secret is no longer available/i)).toBeInTheDocument();
    expect(screen.queryByText(REPLAYED_SECRET)).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: /copy secret/i })).not.toBeInTheDocument();
  });
});

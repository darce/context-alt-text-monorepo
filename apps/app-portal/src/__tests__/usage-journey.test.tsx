import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPortalUsageClient, type PortalUsageClient, type PortalUsageResponse } from '../api/portalUsage';
import { UsageScreen } from '../screens/UsageScreen';

const TENANT_A = '11111111-1111-4111-8111-111111111111';
const TENANT_B = '22222222-2222-4222-8222-222222222222';

type PortalRequest = (path: string, init?: RequestInit) => Promise<Response>;

function mockRequest(impl: PortalRequest) {
  return vi.fn<PortalRequest>(impl);
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function usage(overrides: Partial<PortalUsageResponse> = {}): PortalUsageResponse {
  return {
    tenant_id: TENANT_A,
    used: 3,
    reserved: 1,
    remaining: 6,
    allowance: 10,
    period_start: '2026-09-01T00:00:00Z',
    period_end: '2026-10-01T00:00:00Z',
    period: { start: '2026-09-01T00:00:00Z', end: '2026-10-01T00:00:00Z' },
    as_of: '2026-09-22T12:00:00Z',
    status: 'beta_active',
    data_source: 'authoritative',
    ...overrides,
  };
}

function usageError(status: number, body: unknown) {
  const error = new Error('portal_usage_request_failed') as Error & {
    status: number;
    code: string | null;
    detail: string | null;
    attemptId: string | null;
    retryAfterSeconds: number | null;
  };
  const record = body && typeof body === 'object' ? (body as Record<string, unknown>) : null;
  const detail = record?.detail;
  error.status = status;
  error.code = typeof detail === 'string' ? detail : null;
  error.detail = typeof detail === 'string' ? detail : null;
  error.attemptId = null;
  error.retryAfterSeconds = null;
  return error;
}

function renderUsage(client: PortalUsageClient, sessionKey = 'sess-a') {
  return render(
    <UsageScreen client={client} sessionKey={sessionKey} onNavigateToKeys={vi.fn()} onNavigateToBilling={vi.fn()} />,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('createPortalUsageClient [DATA-03][HAI-01]', () => {
  it('reads GET /portal/usage without tenant selection headers or client arithmetic', async () => {
    const request = mockRequest(async () =>
      jsonResponse(200, usage({ remaining: null, used: 4, allowance: 10, reserved: 2 })),
    );
    const client = createPortalUsageClient(request);
    const result = await client.read();
    expect(request).toHaveBeenCalledTimes(1);
    const [path, init] = request.mock.calls[0] ?? (['', undefined] as const);
    expect(String(path)).toBe('/portal/usage');
    expect(init?.method ?? 'GET').toBe('GET');
    expect(JSON.stringify(init ?? {})).not.toMatch(/tenant/i);
    expect(String(path)).not.toMatch(/tenant_id/);
    expect(result.remaining).toBeNull();
    expect(result.used).toBe(4);
    expect(result.allowance).toBe(10);
    expect(result.reserved).toBe(2);
  });

  it('fails closed on wrong shapes and maps 503 to a typed error', async () => {
    const missingPeriod = createPortalUsageClient(async () =>
      jsonResponse(200, {
        tenant_id: TENANT_A,
        used: 1,
        reserved: 0,
        remaining: 1,
        allowance: 2,
        data_source: 'authoritative',
      }),
    );
    await expect(missingPeriod.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

    const badStatus = createPortalUsageClient(async () =>
      jsonResponse(200, usage({ status: 'unlimited' as PortalUsageResponse['status'] })),
    );
    await expect(badStatus.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

    const zeroAsUnknown = createPortalUsageClient(async () =>
      jsonResponse(200, usage({ used: '0' as unknown as number })),
    );
    await expect(zeroAsUnknown.read()).rejects.toMatchObject({ code: 'invalid_portal_usage_response' });

    const outage = createPortalUsageClient(async () => jsonResponse(503, { detail: 'portal usage unavailable' }));
    await expect(outage.read()).rejects.toMatchObject({ status: 503, code: 'portal usage unavailable' });
  });
});

describe('UsageScreen honest fields and states [HAI-01][RLSE-04][NAV-11]', () => {
  it('renders used, reserved, remaining, and allowance independently, treating null as unknown not zero', async () => {
    const client: PortalUsageClient = {
      read: vi.fn(async () => usage({ used: null, reserved: 0, remaining: null, allowance: 10 })),
    };
    renderUsage(client);
    expect(screen.getByRole('status')).toHaveTextContent(/checking usage/i);
    expect(screen.getByRole('main')).toHaveAttribute('aria-busy', 'true');
    await waitFor(() => {
      expect(screen.getByText(/used:/i)).toHaveTextContent(/unknown/i);
    });
    expect(screen.getByText(/reserved:/i)).toHaveTextContent(/0/);
    expect(screen.getByText(/remaining:/i)).toHaveTextContent(/unknown/i);
    expect(screen.getByText(/allowance:/i)).toHaveTextContent(/10/);
    expect(screen.queryByText(/used:\s*0/i)).not.toBeInTheDocument();
    expect(screen.getByText(/2026-09-01T00:00:00Z/)).toBeInTheDocument();
    expect(screen.getByText(/authoritative/i)).toBeInTheDocument();
    expect(screen.getByText(/2026-09-22T12:00:00Z/)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/not available yet|unknown/i);
  });

  it('explains expired, revoked, past due grace, at-cap, pending, and outage without inventing remaining', async () => {
    const user = userEvent.setup();
    const read = vi
      .fn()
      .mockResolvedValueOnce(usage({ status: 'expired', remaining: 4, used: 6, reserved: 0, allowance: 10 }))
      .mockResolvedValueOnce(usage({ status: 'revoked', remaining: null, used: null, reserved: null, allowance: null }))
      .mockResolvedValueOnce(usage({ status: 'past_due', remaining: 2 }))
      .mockResolvedValueOnce(usage({ status: 'paid_active', remaining: 0, used: 10, reserved: 0, allowance: 10 }))
      .mockResolvedValueOnce(
        usage({
          status: 'beta_active',
          data_source: 'pending',
          used: null,
          reserved: null,
          remaining: null,
          allowance: null,
          as_of: null,
        }),
      )
      .mockRejectedValueOnce(usageError(503, { detail: 'portal usage unavailable' }))
      .mockResolvedValueOnce(usage());
    renderUsage({ read });
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/expired/i);
    });
    expect(screen.getByRole('status')).toHaveTextContent(/closed/i);

    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/revoked/i);
    });
    expect(screen.getByRole('status')).toHaveTextContent(/closed/i);

    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/past due/i);
    });
    expect(screen.getByRole('status')).toHaveTextContent(/grace/i);

    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/cap/i);
    });
    expect(screen.getByText(/remaining:/i)).toHaveTextContent(/0/);

    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/pending|not available yet/i);
    });
    expect(screen.getByText(/as of:/i)).toHaveTextContent(/unavailable/i);

    await user.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/temporarily unavailable/i);
    });
    expect(screen.queryByText(/portal usage unavailable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/used:/i)).not.toBeInTheDocument();
    const retry = screen.getByRole('button', { name: /try again/i });
    expect(retry).toHaveFocus();
    await user.click(retry);
    await waitFor(() => {
      expect(screen.getByText(/used:/i)).toHaveTextContent(/3/);
    });
  });

  it('clears old numbers on identity change and loading, and ignores a late previous-session response', async () => {
    let finishA: ((value: PortalUsageResponse) => void) | undefined;
    const readA = vi.fn(
      () =>
        new Promise<PortalUsageResponse>((resolve) => {
          finishA = resolve;
        }),
    );
    let finishB: ((value: PortalUsageResponse) => void) | undefined;
    const readB = vi.fn(
      () =>
        new Promise<PortalUsageResponse>((resolve) => {
          finishB = resolve;
        }),
    );

    function Harness() {
      const [sessionKey, setSessionKey] = useState('sess-a');
      return (
        <div>
          <button type="button" onClick={() => setSessionKey('sess-b')}>
            switch-session
          </button>
          <UsageScreen
            client={sessionKey === 'sess-a' ? { read: readA } : { read: readB }}
            sessionKey={sessionKey}
            onNavigateToKeys={() => undefined}
            onNavigateToBilling={() => undefined}
          />
        </div>
      );
    }

    const user = userEvent.setup();
    render(<Harness />);
    finishA?.(usage({ used: 42, remaining: 58, reserved: 0, allowance: 100 }));
    await waitFor(() => {
      expect(screen.getByText(/used:/i)).toHaveTextContent(/42/);
    });
    await user.click(screen.getByRole('button', { name: /switch-session/i }));
    expect(screen.queryByText(/42/)).not.toBeInTheDocument();
    expect(screen.queryByText(/58/)).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/checking usage/i);
    finishB?.(usage({ tenant_id: TENANT_B, used: 9, remaining: 1, reserved: 0, allowance: 10 }));
    await waitFor(() => {
      expect(screen.getByText(/used:/i)).toHaveTextContent(/9/);
    });
    expect(screen.queryByText(/42/)).not.toBeInTheDocument();
  });
});

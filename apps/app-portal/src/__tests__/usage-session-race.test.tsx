import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { PortalUsageClient, PortalUsageResponse } from '../api/portalUsage';
import { UsageScreen } from '../screens/UsageScreen';

const TENANT_A = '11111111-1111-4111-8111-111111111111';
const TENANT_B = '22222222-2222-4222-8222-222222222222';

function usage(tenantId: string, used: number): PortalUsageResponse {
  return {
    tenant_id: tenantId,
    used,
    reserved: 0,
    remaining: 100 - used,
    allowance: 100,
    period_start: '2026-09-01T00:00:00Z',
    period_end: '2026-10-01T00:00:00Z',
    period: { start: '2026-09-01T00:00:00Z', end: '2026-10-01T00:00:00Z' },
    as_of: '2026-09-22T12:00:00Z',
    status: 'beta_active',
    data_source: 'authoritative',
  };
}

describe('UsageScreen session response race', () => {
  it('keeps session B usage when the pending session A response arrives late', async () => {
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
      const client: PortalUsageClient = sessionKey === 'sess-a' ? { read: readA } : { read: readB };
      return (
        <div>
          <button type="button" onClick={() => setSessionKey('sess-b')}>
            switch-session
          </button>
          <UsageScreen
            client={client}
            sessionKey={sessionKey}
            onNavigateToKeys={() => undefined}
            onNavigateToBilling={() => undefined}
          />
        </div>
      );
    }

    const user = userEvent.setup();
    render(<Harness />);
    expect(readA).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /switch-session/i }));
    expect(screen.getByRole('status')).toHaveTextContent(/checking usage/i);
    expect(readB).toHaveBeenCalledTimes(1);

    await act(async () => {
      finishB?.(usage(TENANT_B, 9));
    });
    await waitFor(() => {
      expect(screen.getByText(/used:/i)).toHaveTextContent(/9/);
    });

    await act(async () => {
      finishA?.(usage(TENANT_A, 42));
    });

    expect(screen.getByText(/used:/i)).toHaveTextContent(/9/);
    expect(screen.queryByText(/42/)).not.toBeInTheDocument();
  });
});

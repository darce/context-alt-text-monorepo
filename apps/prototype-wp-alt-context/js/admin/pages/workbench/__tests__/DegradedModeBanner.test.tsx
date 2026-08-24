import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { SyncHealthResponse } from '../../../api/recognition/types/sync';
import { SCAN_CONFLICTS_HREF, SCAN_DEAD_LETTER_HREF } from '../../../navigation/appLinks';
import { DegradedModeBannerView } from '../DegradedModeBanner';
import { getDegradedDebtLinks, isSyncOffline, shouldShowDegradedBanner } from '../degradedModeBannerLogic';

const closedHealth: SyncHealthResponse = {
  breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
  outbox: { pending: 0, failed: 0 },
  conflicts: { open: 0 },
  replays: { failed: null, source: 'unavailable_local' },
  last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
  warnings: [],
};

describe('shouldShowDegradedBanner', () => {
  it.each([
    ['open breaker', { ...closedHealth, breaker: { ...closedHealth.breaker, state: 'open' as const } }, true],
    // A latched failed pull with a closed breaker is NOT offline — the service is
    // reachable; the failed outcome self-repairs on the next successful pull.
    ['failed last pull, breaker closed', { ...closedHealth, last_pull: { at: '2026-06-11T12:00:00Z', ok: false } }, false],
    [
      'threshold warning only',
      { ...closedHealth, warnings: [{ code: 'open_conflicts_high', message: 'warn', count: 30, threshold: 25 }] },
      true,
    ],
    ['healthy envelope', closedHealth, false],
  ])('returns %s visibility', (_label, health, expected) => {
    expect(shouldShowDegradedBanner(health)).toBe(expected);
  });
});

describe('isSyncOffline', () => {
  it('returns false for warnings-only health', () => {
    expect(
      isSyncOffline({
        ...closedHealth,
        warnings: [{ code: 'open_conflicts_high', message: 'warn', count: 30, threshold: 25 }],
      }),
    ).toBe(false);
  });
});

describe('getDegradedDebtLinks', () => {
  it('returns workbench overlay links when debt counts are non-zero', () => {
    expect(
      getDegradedDebtLinks({
        ...closedHealth,
        outbox: { pending: 0, failed: 2 },
        conflicts: { open: 3 },
      }),
    ).toEqual({
      failedOutboxHref: SCAN_DEAD_LETTER_HREF,
      conflictsHref: SCAN_CONFLICTS_HREF,
    });
  });
});

describe('DegradedModeBannerView', () => {
  it('keeps live-region nodes stable and empty until initial health loading settles', () => {
    const onRetry = vi.fn();

    const { rerender } = render(
      <DegradedModeBannerView health={undefined} isLoading onRetry={onRetry} />,
    );

    const politeRegion = screen.getByRole('status');
    const assertiveRegion = screen.getByRole('alert');
    expect(politeRegion).toBeEmptyDOMElement();
    expect(assertiveRegion).toBeEmptyDOMElement();
    expect(screen.queryByTestId('acx-degraded-mode-banner')).not.toBeInTheDocument();

    rerender(
      <DegradedModeBannerView health={undefined} isLoading={false} onRetry={onRetry} />,
    );

    expect(screen.getByRole('status')).toBe(politeRegion);
    expect(screen.getByRole('alert')).toBe(assertiveRegion);
    expect(within(assertiveRegion).getByText('Backend health unknown')).toBeInTheDocument();
    expect(screen.getByTestId('acx-degraded-mode-banner')).toHaveTextContent('Backend health unknown');
    screen.getByRole('button', { name: 'Retry health check' }).click();
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it('renders offline copy with icon when breaker is open', () => {
    render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          breaker: { ...closedHealth.breaker, state: 'open' },
        }}
      />,
    );

    const banner = screen.getByRole('alert');
    expect(banner).toBeInTheDocument();
    // A11Y-23: offline transition is announced via assertive live region.
    expect(banner).toHaveAttribute('aria-live', 'assertive');
    expect(screen.getByText('Working offline')).toBeInTheDocument();
    expect(screen.getByText(/local copy/i)).toBeInTheDocument();
    expect(screen.getByTestId('acx-degraded-mode-banner-icon')).toBeInTheDocument();
  });

  it('does not render "Working offline" when only last pull failed and the breaker is closed', () => {
    // Regression guard: a latched last_pull.ok=false on a reachable backend must
    // not surface the assertive offline banner (false-positive fix).
    const { container } = render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          last_pull: { at: '2026-06-11T12:00:00Z', ok: false },
        }}
      />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText('Working offline')).not.toBeInTheDocument();
  });

  it('renders debt recovery links when counts are non-zero', () => {
    render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          breaker: { ...closedHealth.breaker, state: 'open' },
          outbox: { pending: 0, failed: 1 },
          conflicts: { open: 2 },
        }}
      />,
    );

    expect(screen.getByRole('link', { name: /failed sync operations/i })).toHaveAttribute(
      'href',
      SCAN_DEAD_LETTER_HREF,
    );
    expect(screen.getByRole('link', { name: /sync conflicts/i })).toHaveAttribute('href', SCAN_CONFLICTS_HREF);
  });

  it('renders offline reassurance and warning copy when both are present', () => {
    render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          breaker: { ...closedHealth.breaker, state: 'open' },
          warnings: [
            {
              code: 'open_conflicts_high',
              message: 'Open sync conflicts exceed the configured warning threshold.',
              count: 30,
              threshold: 25,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('Working offline')).toBeInTheDocument();
    expect(screen.getByText(/local copy/i)).toBeInTheDocument();
    expect(screen.getByText(/warning threshold/i)).toBeInTheDocument();
  });

  it('renders advisory title and translated warning copy when warnings are present', () => {
    render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          warnings: [
            {
              code: 'open_conflicts_high',
              message: 'Open sync conflicts exceed the configured warning threshold.',
              count: 30,
              threshold: 25,
            },
          ],
        }}
      />,
    );

    // A11Y-23 / rg-004: advisory mode is a polite status region, not an assertive alert.
    const banner = screen.getByRole('status');
    expect(banner).toHaveAttribute('aria-live', 'polite');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Sync attention needed')).toBeInTheDocument();
    expect(screen.queryByText('Working offline')).not.toBeInTheDocument();
    expect(screen.getByText(/warning threshold/i)).toBeInTheDocument();
  });

  it('clears the same live-region nodes when sync health becomes healthy', () => {
    const { rerender } = render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          breaker: { ...closedHealth.breaker, state: 'open' },
        }}
      />,
    );

    const politeRegion = screen.getByRole('status');
    const assertiveRegion = screen.getByRole('alert');
    expect(assertiveRegion).not.toBeEmptyDOMElement();

    rerender(<DegradedModeBannerView health={closedHealth} />);

    expect(screen.getByRole('status')).toBe(politeRegion);
    expect(screen.getByRole('alert')).toBe(assertiveRegion);
    expect(politeRegion).toBeEmptyDOMElement();
    expect(assertiveRegion).toBeEmptyDOMElement();
    expect(screen.queryByTestId('acx-degraded-mode-banner')).not.toBeInTheDocument();
  });
});

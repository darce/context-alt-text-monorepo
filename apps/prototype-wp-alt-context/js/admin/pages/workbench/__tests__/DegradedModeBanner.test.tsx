import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { SyncHealthResponse } from '../../../api/recognition/types/sync';
import { DegradedModeBannerView } from '../DegradedModeBanner';
import { getDegradedDebtLinks, shouldShowDegradedBanner } from '../degradedModeBannerLogic';

const closedHealth: SyncHealthResponse = {
  breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
  outbox: { pending: 0, failed: 0 },
  conflicts: { open: 0 },
  replays: { failed: null, source: 'unavailable_local' },
  last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
};

describe('shouldShowDegradedBanner', () => {
  it.each([
    ['open breaker', { ...closedHealth, breaker: { ...closedHealth.breaker, state: 'open' as const } }, true],
    ['failed last pull', { ...closedHealth, last_pull: { at: '2026-06-11T12:00:00Z', ok: false } }, true],
    ['healthy envelope', closedHealth, false],
  ])('returns %s visibility', (_label, health, expected) => {
    expect(shouldShowDegradedBanner(health)).toBe(expected);
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
      failedOutboxHref: '#/workbench?tab=scan&panel=dead-letter',
      conflictsHref: '#/workbench?tab=scan&panel=conflicts',
    });
  });
});

describe('DegradedModeBannerView', () => {
  it('renders offline copy with icon when breaker is open', () => {
    render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          breaker: { ...closedHealth.breaker, state: 'open' },
        }}
      />,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Working offline')).toBeInTheDocument();
    expect(screen.getByText(/local copy/i)).toBeInTheDocument();
    expect(screen.getByTestId('acx-degraded-mode-banner-icon')).toBeInTheDocument();
  });

  it('renders offline copy when last pull failed', () => {
    render(
      <DegradedModeBannerView
        health={{
          ...closedHealth,
          last_pull: { at: '2026-06-11T12:00:00Z', ok: false },
        }}
      />,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Working offline')).toBeInTheDocument();
    expect(screen.getByText(/local copy/i)).toBeInTheDocument();
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
      '#/workbench?tab=scan&panel=dead-letter',
    );
    expect(screen.getByRole('link', { name: /sync conflicts/i })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=conflicts',
    );
  });

  it('renders nothing when sync health is healthy', () => {
    const { container } = render(<DegradedModeBannerView health={closedHealth} />);

    expect(container).toBeEmptyDOMElement();
  });
});
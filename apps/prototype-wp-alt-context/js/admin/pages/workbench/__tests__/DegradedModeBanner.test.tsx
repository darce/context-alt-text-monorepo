import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { SyncHealthResponse } from '../../../api/recognition/types/sync';
import { DegradedModeBannerView } from '../DegradedModeBanner';
import { shouldShowDegradedBanner } from '../degradedModeBannerLogic';

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

  it('renders nothing when sync health is healthy', () => {
    const { container } = render(<DegradedModeBannerView health={closedHealth} />);

    expect(container).toBeEmptyDOMElement();
  });
});
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { DebugMetrics } from '../../../../api/recognition';
import { isDevMode } from '../../../../api/config';
import { DebugMetricsPanel } from '../DebugMetricsPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/config', () => ({
  isDevMode: vi.fn(),
}));

const mockIsDevMode = vi.mocked(isDevMode);

const metrics: DebugMetrics = {
  pose: { pitch: 5, yaw: 10, roll: 2 },
  det_score: 0.98,
  bbox_area: 12000,
  landmark_quality: 0.9,
  clustering_method: 'similarity_match',
  clustering_algorithm: 'cosine_similarity',
  similarity_threshold: 0.5,
  match_similarity: 0.62,
};

/**
 * E21-5 Slice 8 (§8): the DebugMetricsPanel is dev-gated via `isDevMode()`. This
 * is the regression test locking the gate — the panel must render null outside
 * development, no matter what metrics are present. No rebuild.
 */
describe('DebugMetricsPanel dev gate (§8)', () => {
  beforeEach(() => {
    mockIsDevMode.mockReset();
  });

  it('renders null when isDevMode() is false, even with metrics present', () => {
    mockIsDevMode.mockReturnValue(false);
    const { container } = render(<DebugMetricsPanel metrics={metrics} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the panel when isDevMode() is true (positive control)', () => {
    mockIsDevMode.mockReturnValue(true);
    render(<DebugMetricsPanel metrics={metrics} />);
    expect(screen.getByRole('button', { expanded: false })).toBeInTheDocument();
  });

  it('renders null in dev mode when metrics are absent', () => {
    mockIsDevMode.mockReturnValue(true);
    const { container } = render(<DebugMetricsPanel metrics={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { JobProgress } from '../../../api/recognition/types/scan';
import { buildMilestones, JobTimeline } from '../JobTimeline';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[1-9]?\$?[sd]/g, () => String(args[i++]));
  },
}));

// ---------------------------------------------------------------------------
// buildMilestones — unit tests for milestone derivation logic
// ---------------------------------------------------------------------------

describe('buildMilestones', () => {
  it('returns empty array when phase is idle and no progress', () => {
    const result = buildMilestones(null, null, 'idle', 'idle');
    expect(result).toHaveLength(0);
  });

  it('shows active scan milestone while scanning', () => {
    const scan: JobProgress = { completed: 3, total: 10, phase: 'detecting' };
    const milestones = buildMilestones(scan, null, 'scanning', 'idle');
    const scanM = milestones.find((m) => m.id === 'scan');
    expect(scanM?.status).toBe('active');
    expect(scanM?.label).toBe('Scanning\u2026');
  });

  it('keeps scan active during clustering until the scan job reports a completed phase', () => {
    const scan: JobProgress = { completed: 10, total: 10, images_processed: 10, faces_found: 3, phase: 'detecting' };
    const milestones = buildMilestones(scan, null, 'clustering', 'idle');
    const scanM = milestones.find((m) => m.id === 'scan');
    expect(scanM?.status).toBe('active');
    expect(scanM?.label).toBe('Scanning\u2026');
    expect(scanM?.detail).toContain('10 images');
  });

  it('shows completed scan milestone during clustering when the scan job reports a completed phase', () => {
    const scan: JobProgress = {
      completed: 10,
      total: 10,
      images_processed: 10,
      faces_found: 3,
      phase: 'awaiting_projection',
    };
    const milestones = buildMilestones(scan, null, 'clustering', 'idle');
    const scanM = milestones.find((m) => m.id === 'scan');
    expect(scanM?.status).toBe('completed');
    expect(scanM?.label).toBe('Scan complete');
    expect(scanM?.detail).toContain('10 images');
    expect(scanM?.detail).toContain('3 faces found');
  });

  it('keeps scan active during projecting until the scan job reports a completed phase', () => {
    const scan: JobProgress = { completed: 10, total: 10, images_processed: 10, phase: 'detecting' };
    const milestones = buildMilestones(scan, null, 'projecting', 'syncing');
    const scanM = milestones.find((m) => m.id === 'scan');
    expect(scanM?.status).toBe('active');
    expect(scanM?.label).toBe('Scanning\u2026');
    expect(scanM?.detail).toContain('10 images');
  });

  it('shows active clustering milestone while clustering', () => {
    const cluster: JobProgress = { completed: 5, total: 20, phase: 'clustering' };
    const milestones = buildMilestones(null, cluster, 'clustering', 'idle');
    const clusterM = milestones.find((m) => m.id === 'clustering');
    expect(clusterM?.status).toBe('active');
    expect(clusterM?.detail).toContain('5 / 20 identities');
  });

  it('shows completed clustering milestone with cluster count when done', () => {
    const cluster: JobProgress = {
      completed: 20,
      total: 20,
      phase: 'awaiting_projection',
      clusters_created: 4,
    };
    const milestones = buildMilestones(null, cluster, 'projecting', 'idle');
    const clusterM = milestones.find((m) => m.id === 'clustering');
    expect(clusterM?.status).toBe('completed');
    expect(clusterM?.detail).toBe('4 clusters created');
  });

  it('shows failed clustering milestone when phase is failed', () => {
    const cluster: JobProgress = { completed: 2, total: 10, phase: 'failed', last_error_code: 'timeout' };
    const milestones = buildMilestones(null, cluster, 'clustering', 'idle');
    const clusterM = milestones.find((m) => m.id === 'clustering');
    expect(clusterM?.status).toBe('failed');
    expect(clusterM?.label).toBe('Clustering failed');
  });

  it('emits one retry milestone per retry_count', () => {
    const cluster: JobProgress = {
      completed: 5,
      total: 20,
      phase: 'retrying',
      retry_count: 2,
      last_error_code: 'embed_error',
    };
    const milestones = buildMilestones(null, cluster, 'clustering', 'idle');
    const retryMilestones = milestones.filter((m) => m.id.startsWith('retry-'));
    expect(retryMilestones).toHaveLength(2);
    // Last retry is active (matching current phase)
    expect(retryMilestones[1]?.status).toBe('active');
    expect(retryMilestones[1]?.detail).toContain('embed_error');
    // First retry is completed
    expect(retryMilestones[0]?.status).toBe('completed');
  });

  it('shows active projection milestone while syncing', () => {
    const milestones = buildMilestones(null, null, 'projecting', 'syncing');
    const projM = milestones.find((m) => m.id === 'results');
    expect(projM?.status).toBe('active');
    expect(projM?.label).toBe('Syncing results\u2026');
  });

  it('shows failed projection milestone on error', () => {
    const milestones = buildMilestones(null, null, 'projecting', 'error');
    const projM = milestones.find((m) => m.id === 'results');
    expect(projM?.status).toBe('failed');
    expect(projM?.label).toBe('Results sync failed');
  });

  it('shows acknowledging label during acknowledging state', () => {
    const milestones = buildMilestones(null, null, 'projecting', 'acknowledging');
    const projM = milestones.find((m) => m.id === 'results');
    expect(projM?.status).toBe('active');
    expect(projM?.label).toBe('Confirming results…');
  });

  it('shows clusters_created = 1 with singular label', () => {
    const cluster: JobProgress = {
      completed: 10,
      total: 10,
      phase: 'complete',
      clusters_created: 1,
    };
    const milestones = buildMilestones(null, cluster, 'projecting', 'idle');
    const clusterM = milestones.find((m) => m.id === 'clustering');
    expect(clusterM?.detail).toBe('1 cluster created');
  });
});

// ---------------------------------------------------------------------------
// JobTimeline — render tests
// ---------------------------------------------------------------------------

describe('JobTimeline', () => {
  it('renders nothing when phase is idle and no progress', () => {
    const { container } = render(<JobTimeline scanProgress={null} clusterProgress={null} phase="idle" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders an ordered list with aria-label when milestones exist', () => {
    const scan: JobProgress = { completed: 5, total: 10, phase: 'detecting' };
    render(<JobTimeline scanProgress={scan} clusterProgress={null} phase="scanning" />);
    expect(screen.getByRole('list', { name: 'Job progress milestones' })).toBeTruthy();
  });

  it('renders scanning and clustering-active milestones until the scan job reports completion', () => {
    const scan: JobProgress = { completed: 10, total: 10, images_processed: 10, faces_found: 2, phase: 'detecting' };
    const cluster: JobProgress = { completed: 3, total: 15, phase: 'clustering' };
    render(<JobTimeline scanProgress={scan} clusterProgress={cluster} phase="clustering" />);
    expect(screen.getByText('Scanning\u2026')).toBeTruthy();
    expect(screen.getByText('Clustering\u2026')).toBeTruthy();
  });

  it('keeps the scan milestone active during projecting until scanProgress reaches a completed phase', () => {
    const scan: JobProgress = { completed: 10, total: 10, images_processed: 10, faces_found: 2, phase: 'detecting' };
    render(<JobTimeline scanProgress={scan} clusterProgress={null} phase="projecting" projectionSyncState="syncing" />);
    expect(screen.getByText('Scanning\u2026')).toBeTruthy();
    expect(screen.queryByText('Scan complete')).toBeNull();
    expect(screen.getByText('Syncing results\u2026')).toBeTruthy();
  });

  it('renders retry milestone with error detail', () => {
    const cluster: JobProgress = {
      completed: 2,
      total: 10,
      phase: 'retrying',
      retry_count: 1,
      last_error_code: 'vector_mismatch',
    };
    render(<JobTimeline scanProgress={null} clusterProgress={cluster} phase="clustering" />);
    expect(screen.getByText('Retry 1')).toBeTruthy();
    expect(screen.getByText('Last error: vector_mismatch')).toBeTruthy();
  });

  it('renders projection syncing milestone', () => {
    render(<JobTimeline scanProgress={null} clusterProgress={null} phase="projecting" projectionSyncState="syncing" />);
    expect(screen.getByText('Syncing results\u2026')).toBeTruthy();
  });

  it('renders projection ready milestone after sync completes', () => {
    render(<JobTimeline scanProgress={null} clusterProgress={null} phase="projecting" projectionSyncState="ready" />);
    expect(screen.getByText('Results ready for review')).toBeTruthy();
  });

  it('applies compact layout class and omits detail text', () => {
    const scan: JobProgress = { completed: 5, total: 10, phase: 'detecting', images_processed: 5 };
    const { container } = render(
      <JobTimeline compact scanProgress={scan} clusterProgress={null} phase="scanning" />,
    );
    const list = container.querySelector('.acx-job-timeline--compact');
    expect(list).toBeTruthy();
    expect(list?.getAttribute('data-compact')).toBe('true');
    expect(screen.getByText('Scanning\u2026')).toBeTruthy();
    // Compact mode suppresses the detail channel to keep the strip single-line.
    expect(screen.queryByText(/images/i)).toBeNull();
  });
});

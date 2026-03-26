/**
 * Tests for polling behaviour of recognition status hooks.
 *
 * Phase 4 of rls-seam-fixes-and-polling-correction.md:
 * The `useScanStatus` and `useMultiScanStatus` hooks must continue polling
 * when a completed job is still in the `awaiting_projection` phase so the UI
 * stays live until the projection acknowledges.
 */
import { describe, it, expect } from 'vitest';
import type { JobStatusResponse } from '../../api/recognition';
import { getJobRefetchInterval } from '../useRecognitionHooks';
import { derivePipelinePhase } from '../jobStateMachineUtils';

// ---------------------------------------------------------------------------
// Tests — exercise the real exported predicate from useRecognitionHooks
// ---------------------------------------------------------------------------

describe('recognition polling interval', () => {
  it('returns 1500 when status is running', () => {
    const data = { status: 'running' } as JobStatusResponse;
    expect(getJobRefetchInterval(data)).toBe(1500);
  });

  it('returns 1500 when status is pending', () => {
    const data = { status: 'pending' } as JobStatusResponse;
    expect(getJobRefetchInterval(data)).toBe(1500);
  });

  it('returns false when status is completed with no awaiting_projection phase', () => {
    const data = {
      status: 'completed',
      progress: { phase: 'complete' },
    } as unknown as JobStatusResponse;
    expect(getJobRefetchInterval(data)).toBe(false);
  });

  it('returns 1500 when status is completed but phase is awaiting_projection', () => {
    const data = {
      status: 'completed',
      progress: { phase: 'awaiting_projection' },
    } as unknown as JobStatusResponse;
    expect(getJobRefetchInterval(data)).toBe(1500);
  });

  it('returns false when status is completed and progress is undefined', () => {
    const data = { status: 'completed' } as JobStatusResponse;
    expect(getJobRefetchInterval(data)).toBe(false);
  });

  it('returns false when data is undefined', () => {
    expect(getJobRefetchInterval(undefined)).toBe(false);
  });

  it('returns 1500 when status is failed but phase is awaiting_projection', () => {
    // Edge: job reached completed state mid-projection then re-queued;
    // polling must continue if phase indicates work is in progress.
    const data = {
      status: 'failed',
      progress: { phase: 'awaiting_projection' },
    } as unknown as JobStatusResponse;
    expect(getJobRefetchInterval(data)).toBe(1500);
  });

  it('returns false when status is completed with phase complete and projection_acknowledged_at set', () => {
    // Second-poll scenario: backend has acknowledged projection; the UI must stop polling.
    const data = {
      status: 'completed',
      progress: { phase: 'complete' },
      projection_acknowledged_at: '2026-03-25T00:01:30Z',
    } as unknown as JobStatusResponse;
    expect(getJobRefetchInterval(data)).toBe(false);
  });

  it('transitions: polling continues at awaiting_projection then stops when phase becomes complete', () => {
    const firstPoll = {
      status: 'completed',
      progress: { phase: 'awaiting_projection' },
    } as unknown as JobStatusResponse;
    expect(getJobRefetchInterval(firstPoll)).toBe(1500);

    const secondPoll = {
      status: 'completed',
      progress: { phase: 'complete' },
      projection_acknowledged_at: '2026-03-25T00:01:30Z',
    } as unknown as JobStatusResponse;
    expect(getJobRefetchInterval(secondPoll)).toBe(false);
  });
});

describe('derivePipelinePhase exits projecting state', () => {
  it('returns idle when phase transitions from awaiting_projection to complete with projection acknowledged', () => {
    // Simulate the follow-up poll after projection is done.
    // derivePipelinePhase must not return "projecting" once phase != awaiting_projection.
    const secondPoll = {
      id: 'job-1',
      type: 'clustering',
      status: 'completed',
      progress: { completed: 10, total: 10, phase: 'complete' },
      started_at: '2026-03-25T00:00:00Z',
      finished_at: '2026-03-25T00:01:00Z',
      projection_acknowledged_at: '2026-03-25T00:01:30Z',
    } as unknown as JobStatusResponse;

    const phase = derivePipelinePhase(null, null, secondPoll);
    expect(phase).toBe('idle');
  });

  it('returns projecting when phase is awaiting_projection regardless of projection_acknowledged_at', () => {
    const firstPoll = {
      id: 'job-1',
      type: 'clustering',
      status: 'completed',
      progress: { completed: 10, total: 10, phase: 'awaiting_projection' },
      started_at: '2026-03-25T00:00:00Z',
      finished_at: null,
      projection_acknowledged_at: null,
    } as unknown as JobStatusResponse;

    // latestClusterJob is non-null so the projecting condition is satisfied.
    const phase = derivePipelinePhase(null, { id: 'job-1', type: 'clustering' } as never, firstPoll);
    expect(phase).toBe('projecting');
  });

  it('returns projecting when phase is awaiting_projection even without local active jobs', () => {
    const poll = {
      id: 'job-1',
      type: 'clustering',
      status: 'completed',
      progress: { completed: 10, total: 10, phase: 'awaiting_projection' },
      started_at: '2026-03-25T00:00:00Z',
      finished_at: null,
      projection_acknowledged_at: null,
    } as unknown as JobStatusResponse;

    // Backend auto-chained clustering: no local scan or cluster job exists.
    const phase = derivePipelinePhase(null, null, poll);
    expect(phase).toBe('projecting');
  });
});

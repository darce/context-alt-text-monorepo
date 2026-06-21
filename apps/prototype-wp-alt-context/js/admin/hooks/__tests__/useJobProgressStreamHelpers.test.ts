import { createRef } from 'react';
import { describe, expect, it } from 'vitest';

import type { JobProgress } from '../../api/recognition/types/scan';
import { parseDoneEvent, parseProgressEvent } from '../useJobProgressStreamHelpers';

// ---------------------------------------------------------------------------
// parseProgressEvent
// ---------------------------------------------------------------------------

describe('parseProgressEvent', () => {
  it('returns null for invalid JSON', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    expect(parseProgressEvent('not-json', ref)).toBeNull();
  });

  it('returns null when completed/total are non-numeric or absent (COR-4: sr-005 SSE boundary validation)', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    expect(parseProgressEvent(JSON.stringify({ status: 'running', total: null }), ref)).toBeNull();
    expect(parseProgressEvent(JSON.stringify({ status: 'running', completed: '3', total: 10 }), ref)).toBeNull();
    expect(parseProgressEvent(JSON.stringify({ status: 'running' }), ref)).toBeNull();
    expect(ref.current).toBeNull();
  });

  it('parses basic completed/total/status', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    const result = parseProgressEvent<'scanning'>(JSON.stringify({ completed: 3, total: 10, status: 'scanning' }), ref);
    expect(result).not.toBeNull();
    expect(result!.progress.completed).toBe(3);
    expect(result!.progress.total).toBe(10);
    expect(result!.status).toBe('scanning');
  });

  it('populates all checkpoint fields from payload', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    const payload = {
      completed: 5,
      total: 20,
      status: 'clustering',
      phase: 'clustering',
      images_processed: 5,
      faces_found: 10,
      clusters_created: 3,
      retry_count: 1,
      current_stage: 'assign',
      last_successful_processed_identities: 4,
      last_error_code: 'timeout',
    };
    const result = parseProgressEvent<'clustering'>(JSON.stringify(payload), ref);
    expect(result).not.toBeNull();
    const p = result!.progress;
    expect(p.phase).toBe('clustering');
    expect(p.images_processed).toBe(5);
    expect(p.faces_found).toBe(10);
    expect(p.clusters_created).toBe(3);
    expect(p.retry_count).toBe(1);
    expect(p.current_stage).toBe('assign');
    expect(p.last_successful_processed_identities).toBe(4);
    expect(p.last_error_code).toBe('timeout');
  });

  it('does not set optional fields when absent from payload', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    const result = parseProgressEvent<'scanning'>(JSON.stringify({ completed: 1, total: 5, status: 'scanning' }), ref);
    expect(result).not.toBeNull();
    expect(result!.progress.phase).toBeUndefined();
    expect(result!.progress.retry_count).toBeUndefined();
    expect(result!.progress.last_error_code).toBeUndefined();
  });

  it('sets startTimeRef.current on first non-zero progress', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    expect(ref.current).toBeNull();
    parseProgressEvent(JSON.stringify({ completed: 1, total: 10, status: 's' }), ref);
    expect(ref.current).toBeTypeOf('number');
  });

  it('does not set startTimeRef.current when completed is 0', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    parseProgressEvent(JSON.stringify({ completed: 0, total: 10, status: 's' }), ref);
    expect(ref.current).toBeNull();
  });

  it('does not overwrite existing startTimeRef.current', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = 12345;
    parseProgressEvent(JSON.stringify({ completed: 5, total: 10, status: 's' }), ref);
    expect(ref.current).toBe(12345);
  });

  it('returns etaSeconds when elapsed time and progress are available', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    // Simulate a start time 10 seconds ago
    ref.current = Date.now() - 10_000;
    const result = parseProgressEvent(JSON.stringify({ completed: 5, total: 10, status: 's' }), ref);
    expect(result).not.toBeNull();
    // 5 remaining at same rate → approx 10s ETA; just verify it's a non-null number
    expect(result!.etaSeconds).toBeTypeOf('number');
    expect(result!.etaSeconds).toBeGreaterThan(0);
  });

  it('returns etaSeconds null when completed is 0', () => {
    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = null;
    const result = parseProgressEvent(JSON.stringify({ completed: 0, total: 10, status: 's' }), ref);
    expect(result).not.toBeNull();
    expect(result!.etaSeconds).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// parseDoneEvent
// ---------------------------------------------------------------------------

describe('parseDoneEvent', () => {
  it('returns null for invalid JSON', () => {
    expect(parseDoneEvent('not-json', null)).toBeNull();
  });

  it('uses explicit completed/total from payload', () => {
    const result = parseDoneEvent<'completed'>(JSON.stringify({ status: 'completed', completed: 42, total: 42 }), null);
    expect(result).not.toBeNull();
    expect(result!.progress!.completed).toBe(42);
    expect(result!.progress!.total).toBe(42);
    expect(result!.status).toBe('completed');
  });

  it('populates all checkpoint fields from done payload', () => {
    const payload = {
      status: 'completed',
      completed: 100,
      total: 100,
      phase: 'complete',
      images_processed: 100,
      faces_found: 25,
      clusters_created: 8,
      retry_count: 0,
      current_stage: 'done',
      last_successful_processed_identities: 99,
      last_error_code: null,
    };
    const result = parseDoneEvent<'completed'>(JSON.stringify(payload), null);
    expect(result).not.toBeNull();
    const p = result!.progress!;
    expect(p.phase).toBe('complete');
    expect(p.images_processed).toBe(100);
    expect(p.faces_found).toBe(25);
    expect(p.clusters_created).toBe(8);
    expect(p.retry_count).toBe(0);
    expect(p.current_stage).toBe('done');
    expect(p.last_successful_processed_identities).toBe(99);
  });

  it('falls back to latestProgress when status is completed and no counts in payload', () => {
    const latest: JobProgress = { completed: 50, total: 50 };
    const result = parseDoneEvent<'completed'>(JSON.stringify({ status: 'completed' }), latest);
    expect(result).not.toBeNull();
    expect(result!.progress!.completed).toBe(50);
    expect(result!.progress!.total).toBe(50);
  });

  it('finalizes progress for a completed_with_errors done event without counts (BND-1-AUDIT-2)', () => {
    // The done-event success gate must accept completed_with_errors, not just 'completed'. Defensive:
    // the live WP producer always sends counts (first branch), but a counts-less partial-success
    // done event must still FINALIZE progress (completed := total). latest is deliberately unequal
    // (30/50) so the fix's branch (-> 50/50) is distinguishable from the buggy passthrough (30/50).
    const latest: JobProgress = { completed: 30, total: 50 };
    const result = parseDoneEvent<'completed_with_errors'>(JSON.stringify({ status: 'completed_with_errors' }), latest);
    expect(result).not.toBeNull();
    expect(result!.progress!.completed).toBe(50);
    expect(result!.progress!.total).toBe(50);
    expect(result!.status).toBe('completed_with_errors');
  });

  it('returns latestProgress for non-completed status without counts', () => {
    const latest: JobProgress = { completed: 30, total: 50 };
    const result = parseDoneEvent<'failed'>(JSON.stringify({ status: 'failed' }), latest);
    expect(result).not.toBeNull();
    expect(result!.status).toBe('failed');
    expect(result!.progress).toBe(latest);
  });

  it('returns null progress when no latestProgress and no counts', () => {
    const result = parseDoneEvent<'failed'>(JSON.stringify({ status: 'failed' }), null);
    expect(result).not.toBeNull();
    expect(result!.progress).toBeNull();
  });
});

import { createRef } from 'react';
import { describe, expect, it } from 'vitest';

import type { JobProgress } from '../../api/recognition/types/scan';
import {
  parseDoneEvent,
  parseProgressEvent,
  type ParsedProgressEvent,
} from '../useJobProgressStreamHelpers';

const newRef = (initial: number | null = null): React.MutableRefObject<number | null> => {
  const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
  ref.current = initial;
  return ref;
};

/**
 * Internal invariant only (sr-005): the payloads below are fixtures this file wrote, so a
 * failed parse is a defect in the code under test, not untrusted input to validate.
 */
// WHY the disable below: TypeScript assertion signatures ("asserts x is T") are only callable when
// declared as a function declaration, or as a const carrying an explicit type annotation. The bare
// arrow-expression form func-style asks for makes every call site fail with TS2775. sr-005 mandates
// assertion helpers for internal invariants, so the language constraint wins over the style rule.
// eslint-disable-next-line func-style
function assertParsed<TStatus extends string>(
  result: ParsedProgressEvent<TStatus>,
): asserts result is Extract<ParsedProgressEvent<TStatus>, { ok: true }> {
  if (!result.ok) {
    throw new Error(`expected a parsed progress event, got reason="${result.reason}"`);
  }
}

// ---------------------------------------------------------------------------
// parseProgressEvent
// ---------------------------------------------------------------------------

describe('parseProgressEvent', () => {
  it('[FEBT1-LA-04] reports reason "json" for a syntactically invalid frame', () => {
    expect(parseProgressEvent('not-json', newRef())).toEqual({ ok: false, reason: 'json' });
  });

  it('[FEBT1-LA-04] reports reason "schema" when completed/total are non-numeric or absent', () => {
    const ref = newRef();
    // A frame that parsed as JSON but failed validation is producer contract drift, not a
    // corrupt frame: collapsing both onto one boolean made the two indistinguishable in logs.
    expect(parseProgressEvent(JSON.stringify({ status: 'running', total: null }), ref)).toEqual({
      ok: false,
      reason: 'schema',
    });
    expect(parseProgressEvent(JSON.stringify({ status: 'running', completed: '3', total: 10 }), ref)).toEqual({
      ok: false,
      reason: 'schema',
    });
    expect(parseProgressEvent(JSON.stringify({ status: 'running' }), ref)).toEqual({ ok: false, reason: 'schema' });
    expect(ref.current).toBeNull();
  });

  it('[FEBT1-LA-04] a valid JSON array is a schema failure, not a json failure', () => {
    expect(parseProgressEvent(JSON.stringify([1, 2, 3]), newRef())).toEqual({ ok: false, reason: 'schema' });
  });

  it('parses basic completed/total/status', () => {
    const result = parseProgressEvent<'scanning'>(
      JSON.stringify({ completed: 3, total: 10, status: 'scanning' }),
      newRef(),
    );
    assertParsed(result);
    expect(result.progress.completed).toBe(3);
    expect(result.progress.total).toBe(10);
    expect(result.status).toBe('scanning');
  });

  it('populates all checkpoint fields from payload', () => {
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
    const result = parseProgressEvent<'clustering'>(JSON.stringify(payload), newRef());
    assertParsed(result);
    const p = result.progress;
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
    const result = parseProgressEvent<'scanning'>(
      JSON.stringify({ completed: 1, total: 5, status: 'scanning' }),
      newRef(),
    );
    assertParsed(result);
    expect(result.progress.phase).toBeUndefined();
    expect(result.progress.retry_count).toBeUndefined();
    expect(result.progress.last_error_code).toBeUndefined();
  });

  it('sets startTimeRef.current on first non-zero progress', () => {
    const ref = newRef();
    expect(ref.current).toBeNull();
    parseProgressEvent(JSON.stringify({ completed: 1, total: 10, status: 's' }), ref);
    expect(ref.current).toBeTypeOf('number');
  });

  it('does not set startTimeRef.current when completed is 0', () => {
    const ref = newRef();
    parseProgressEvent(JSON.stringify({ completed: 0, total: 10, status: 's' }), ref);
    expect(ref.current).toBeNull();
  });

  it('does not overwrite existing startTimeRef.current', () => {
    const ref = newRef(12345);
    parseProgressEvent(JSON.stringify({ completed: 5, total: 10, status: 's' }), ref);
    expect(ref.current).toBe(12345);
  });

  it('returns etaSeconds when elapsed time and progress are available', () => {
    // Simulate a start time 10 seconds ago
    const result = parseProgressEvent(JSON.stringify({ completed: 5, total: 10, status: 's' }), newRef(Date.now() - 10_000));
    assertParsed(result);
    // 5 remaining at same rate -> approx 10s ETA; just verify it's a non-null number
    expect(result.etaSeconds).toBeTypeOf('number');
    expect(result.etaSeconds).toBeGreaterThan(0);
  });

  it('returns etaSeconds null when completed is 0', () => {
    const result = parseProgressEvent(JSON.stringify({ completed: 0, total: 10, status: 's' }), newRef());
    assertParsed(result);
    expect(result.etaSeconds).toBeNull();
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

  it('[FEBT1-LA-03] carries items_failed through as failedCount', () => {
    // Field name verified against build_stream_progress_payload() in
    // class-job-progress-stream-service.php, which emits absint( items_failed ).
    const result = parseDoneEvent<'completed_with_errors'>(
      JSON.stringify({ status: 'completed_with_errors', completed: 10, total: 10, items_failed: 3 }),
      null,
    );
    expect(result).not.toBeNull();
    expect(result!.failedCount).toBe(3);
  });

  it('[FEBT1-LA-03] carries a zero items_failed rather than dropping it', () => {
    const result = parseDoneEvent<'completed'>(
      JSON.stringify({ status: 'completed', completed: 10, total: 10, items_failed: 0 }),
      null,
    );
    expect(result).not.toBeNull();
    expect(result!.failedCount).toBe(0);
  });

  it('[FEBT1-LA-03] omits failedCount entirely when the wire carried no items_failed (rg-015)', () => {
    const result = parseDoneEvent<'completed_with_errors'>(
      JSON.stringify({ status: 'completed_with_errors', completed: 10, total: 10 }),
      null,
    );
    expect(result).not.toBeNull();
    expect(result).not.toHaveProperty('failedCount');
  });

  it.each([['-1', -1], ['NaN', Number.NaN], ['string', '3']] as const)(
    '[FEBT1-LA-03] rejects a non-count items_failed (%s) instead of forwarding it',
    (_label, value) => {
      const result = parseDoneEvent<'completed_with_errors'>(
        JSON.stringify({ status: 'completed_with_errors', completed: 10, total: 10, items_failed: value }),
        null,
      );
      expect(result).not.toBeNull();
      expect(result).not.toHaveProperty('failedCount');
    },
  );

  it('[FEBT1-LA-03] carries failedCount on the latestProgress fallback path too', () => {
    const latest: JobProgress = { completed: 30, total: 50 };
    const result = parseDoneEvent<'failed'>(JSON.stringify({ status: 'failed', items_failed: 7 }), latest);
    expect(result).not.toBeNull();
    expect(result!.failedCount).toBe(7);
    expect(result!.progress).toBe(latest);
  });
});

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { parseProgressEvent } from '../useJobProgressStreamHelpers';

interface EtaRunLog {
  total: number;
  mid_batch_completed: number;
  elapsed_seconds_at_mid_batch: number;
  actual_remaining_seconds_at_mid_batch: number;
  tolerance_percent: number;
}

const runLogPath = resolve(__dirname, '../../../../../../docs/operations/wbux-3-eta-run-log.json');

describe('bulk describe ETA tolerance proof', () => {
  it('keeps mid-batch ETA within the documented tolerance band', () => {
    const runLog = JSON.parse(readFileSync(runLogPath, 'utf8')) as EtaRunLog;
    const startTime = 1_000_000;
    const now = startTime + runLog.elapsed_seconds_at_mid_batch * 1000;
    vi.spyOn(Date, 'now').mockReturnValue(now);

    const ref = createRef<number | null>() as React.MutableRefObject<number | null>;
    ref.current = startTime;
    const parsed = parseProgressEvent(
      JSON.stringify({
        completed: runLog.mid_batch_completed,
        total: runLog.total,
        status: 'running',
        phase: 'describing',
      }),
      ref,
    );

    expect(parsed?.etaSeconds).not.toBeNull();
    const errorRatio =
      Math.abs((parsed?.etaSeconds ?? 0) - runLog.actual_remaining_seconds_at_mid_batch) /
      runLog.actual_remaining_seconds_at_mid_batch;
    expect(errorRatio).toBeLessThanOrEqual(runLog.tolerance_percent / 100);
  });
});

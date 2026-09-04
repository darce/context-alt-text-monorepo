/**
 * FEBT1-LC-01 / RES-04: `commitClusterToRosterEntry` used to accept no `AbortSignal`, so a
 * caller-side deadline abandoned the caller while the POST kept running server-side — a
 * timeout that only abandons the caller still leaks the resource. These tests hold the
 * transport-level guarantee: the signal reaches `fetch`, and aborting it rejects the request.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// FEBT2-LA-NEW-01: this import order is no longer load-bearing. The cycle
// `api/config -> utils/logger -> utils/appError -> {utils/http, api/config}` was
// broken by extracting `utils/errorTaxonomy`, and the graph is now pinned acyclic by
// js/admin/utils/__tests__/httpModuleGraph.test.ts. Kept as-is only to avoid churn.
import { commitClusterToRosterEntry } from '../rosterApi';
import { registerConfig, resetConfigCache } from '../config';

describe('commitClusterToRosterEntry cancellation [FEBT1-LC-01]', () => {
  beforeEach(() => {
    resetConfigCache();
    registerConfig({
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: { rosterClusters: '/acx/v1/roster/clusters' },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetConfigCache();
    delete window.AltContextAdmin;
  });

  it('forwards the caller signal to the transport', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ person_name: 'Alice' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );

    const controller = new AbortController();
    await commitClusterToRosterEntry({ clusterId: 'c-1', rosterEntryId: 7 }, controller.signal);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const forwarded = fetchSpy.mock.calls[0]?.[1]?.signal;
    expect(forwarded).toBeInstanceOf(AbortSignal);
    // The composed signal must actually follow the caller's controller — an unrelated
    // signal object would satisfy `toBeInstanceOf` while cancelling nothing.
    expect(forwarded?.aborted).toBe(false);
    controller.abort(new DOMException('budget expired', 'TimeoutError'));
    expect(forwarded?.aborted).toBe(true);
  });

  it('rejects when the caller aborts an in-flight commit', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'));
          });
        }),
    );

    const controller = new AbortController();
    const pending = commitClusterToRosterEntry({ clusterId: 'c-1', rosterEntryId: 7 }, controller.signal);
    const assertion = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await assertion;
  });

  it('rejects immediately when the signal is already aborted', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const controller = new AbortController();
    controller.abort();

    await expect(
      commitClusterToRosterEntry({ clusterId: 'c-1', rosterEntryId: 7 }, controller.signal),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache, registerConfig } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { PersonCommitControl } from '../PersonCommitControl';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicit) =>
      String(values[explicit ? Number(explicit) - 1 : index++] ?? ''),
    );
  },
}));

const CLUSTER_ID = 'cluster-unnamed';
const CANONICAL_NAME = 'Ellyn Heald';
const STALE_NAME = 'Gilded Cypress';
const PERSON_ID = 7;
const person: RosterEntry = {
  id: PERSON_ID,
  name: CANONICAL_NAME,
  person_uuid: 'person-7',
  tags: [],
  cluster_count: 1,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-10-15T00:00:00Z',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: '2026-10-15T00:00:00Z',
};
const candidateBody = {
  model_id: 'fixture-model',
  embedding_model: 'fixture-model',
  computed_at: '2026-10-15T00:00:00Z',
  probe_face_count: 1,
  reference_face_count: 2,
  quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates: [
    { cluster_id: 'cluster-ellyn', name: STALE_NAME, similarity: 0.12, band: 'none', roster_entry_id: PERSON_ID },
  ],
};
interface RequestRecord {
  url: URL;
  method: string;
}
let requests: RequestRecord[];
let unexpectedRoutes: string[];
let candidateStatus: number;
let client: ReturnType<typeof buildTestQueryClient>;
const candidateRequests = () => requests.filter(({ url }) => url.pathname.endsWith('/roster-candidates'));
const writeRequests = () => requests.filter(({ method }) => method !== 'GET');
const json = (body: unknown, status = 200): Promise<Response> =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );

beforeEach(() => {
  vi.clearAllMocks();
  requests = [];
  unexpectedRoutes = [];
  candidateStatus = 200;
  registerConfig({
    nonce: 'fixture-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      rosterEntries: '/wp-json/acx/v1/roster/entries',
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
    },
  });
  client = buildTestQueryClient();
  client.setQueryData(queryKeys.roster.entries(), [person]);

  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, window.location.origin);
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      requests.push({ url, method });
      if (method === 'GET' && url.pathname === `/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}/roster-candidates`) {
        return candidateStatus === 200 ? json(candidateBody) : json({ code: 'service_unavailable' }, candidateStatus);
      }
      if (method === 'GET' && url.pathname === '/wp-json/acx/v1/roster/entries') {
        return json([person]);
      }
      unexpectedRoutes.push(`${method} ${url.pathname}`);
      return json({ code: 'unexpected_fixture_route' }, 500);
    }),
  );
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(unexpectedRoutes, 'every request must match an explicit HTTP fixture').toEqual([]);
});

type Props = React.ComponentProps<typeof PersonCommitControl>;
const closestKey = queryKeys.clusters.rosterCandidates(CLUSTER_ID, 5);
const settle = async () => {
  await waitFor(() => expect(client.isFetching()).toBe(0));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
};
const mount = (overrides: Partial<Props> = {}) => {
  const props: Props = {
    clusterId: CLUSTER_ID,
    isPrimary: true,
    phase: 'idle',
    errorMessage: null,
    onCommit: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  };
  const view = render(<PersonCommitControl {...props} />, { wrapper: createQueryWrapper(client) });
  return {
    ...view,
    onCommit: props.onCommit,
    update: (next: Partial<Props>) => view.rerender(<PersonCommitControl {...props} {...next} />),
  };
};
const openNaming = () => {
  const input = screen.getByRole('combobox', { name: 'Name this person' });
  fireEvent.focus(input);
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  return input;
};
const primeFailedCache = async () => {
  const input = openNaming();
  expect(await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ })).toHaveTextContent(
    /weak match/i,
  );
  candidateStatus = 503;
  await act(async () => {
    await client.invalidateQueries({ queryKey: closestKey });
  });
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load name suggestions.');
  await settle();
  expect(candidateRequests()).toHaveLength(2);
  return input;
};

describe('PersonCommitControl busy candidate reads', () => {
  it.each([
    ['external write', { disabled: true }],
    ['person commit', { phase: 'committing' }],
  ] as const)('retains failed-read cache through %s and recovers on idle', async (_label, busy) => {
    const view = mount();
    const input = await primeFailedCache();
    const user = userEvent.setup();
    await user.type(input, 'Zoe');
    view.update(busy);

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load name suggestions.');
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect(retry).toBeDisabled();
    expect(input).toBeDisabled();
    expect(input).toHaveValue('Zoe');
    expect(screen.getByRole('button', { name: 'phase' in busy ? 'Saving name…' : /Create person/ })).toBeDisabled();
    // Pending commits already close the overlay; external holds keep its cached rows.
    if (!('phase' in busy)) {
      expect(screen.getByRole('option', { name: /Confirm match with Ellyn Heald/ })).toHaveTextContent(/weak match/i);
    }
    await user.click(retry);
    fireEvent.keyDown(input, { key: 'Enter' });
    await act(async () => {
      await client.invalidateQueries({ queryKey: closestKey });
    });
    await settle();
    expect(candidateRequests()).toHaveLength(2);
    expect(view.onCommit).not.toHaveBeenCalled();
    expect(writeRequests()).toHaveLength(0);

    candidateStatus = 200;
    view.update({ phase: 'idle', disabled: false });
    await waitFor(() => expect(input).toBeEnabled());
    await waitFor(() => expect(candidateRequests()).toHaveLength(3));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    openNaming();
    expect(await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ })).toHaveTextContent(
      /weak match/i,
    );
    expect(input).toHaveValue('Zoe');
    expect(view.onCommit).not.toHaveBeenCalled();
    await user.click(screen.getByRole('option', { name: /Confirm match with Ellyn Heald/ }));
    expect(view.onCommit).toHaveBeenCalledExactlyOnceWith({ clusterId: CLUSTER_ID, rosterEntryId: PERSON_ID });
    expect(writeRequests()).toHaveLength(0);
  });

  it.each([
    ['NAME', { suggestedCreateName: 'Morgan' }],
    ['ASSIGNMENT', { hasEligiblePendingProposal: true }],
  ] as const)('hard-masks cached machine choices and errors for pending %s', async (_label, pending) => {
    const view = mount();
    await primeFailedCache();
    view.update(pending);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    const input = openNaming();
    expect(screen.queryByText(/weak match/i)).not.toBeInTheDocument();
    expect(input).toBeEnabled();
    // Ordinary roster lookup remains available across the hard model-label boundary.
    fireEvent.change(input, { target: { value: CANONICAL_NAME } });
    expect(screen.getByRole('option', { name: /Confirm match with Ellyn Heald/ })).not.toHaveTextContent(/weak match/i);
    await act(async () => {
      await client.invalidateQueries({ queryKey: closestKey });
    });
    await settle();
    expect(candidateRequests()).toHaveLength(2);
    expect(view.onCommit).not.toHaveBeenCalled();
    expect(writeRequests()).toHaveLength(0);
  });

  it('makes no candidate read when initially busy and fetches once after idle', async () => {
    const view = mount({ disabled: true });
    await settle();
    expect(candidateRequests()).toHaveLength(0);
    expect(screen.getByRole('combobox')).toBeDisabled();
    view.update({ disabled: false });
    openNaming();
    expect(await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ })).toHaveTextContent(
      /weak match/i,
    );
    expect(candidateRequests()).toHaveLength(1);
    expect(view.onCommit).not.toHaveBeenCalled();
    expect(writeRequests()).toHaveLength(0);
  });

  it('masks cached choices and errors after success without a candidate GET', async () => {
    const view = mount();
    await primeFailedCache();
    view.update({ phase: 'succeeded', committedPersonUuid: person.person_uuid });
    expect(screen.getByRole('status')).toHaveTextContent('Name saved.');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await act(async () => {
      await client.invalidateQueries({ queryKey: closestKey });
    });
    await settle();
    expect(candidateRequests()).toHaveLength(2);
    expect(view.onCommit).not.toHaveBeenCalled();
    expect(writeRequests()).toHaveLength(0);
  });
});

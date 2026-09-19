import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../api/config';
import { listRosterEntries, type RosterEntry } from '../../../api/rosterApi';
import { fetchRequiredApi } from '../../../utils/http';
import { PersonWorkspacePanel } from '../PersonWorkspacePanel';

vi.mock('../../../api/recognition/clusterApiMutations', () => ({
  pinRepresentative: vi.fn(),
}));

vi.mock('../../../api/rosterApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../api/rosterApi')>();
  return {
    ...actual,
    listRosterEntries: vi.fn(),
  };
});

vi.mock('../../../utils/http', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../utils/http')>();
  return {
    ...actual,
    fetchRequiredApi: vi.fn(),
  };
});

const CLUSTER_UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

const rosterPerson = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: 'person-uuid-1',
  name: 'Alice',
  tags: [],
  cluster_count: 0,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-05-07T12:00:00Z',
  source_version: 11,
  projection_status: 'current',
  projection_refreshed_at: '2026-05-07T12:00:00Z',
  ...overrides,
});

const alice = rosterPerson();
const bob = rosterPerson({ id: 2, person_uuid: 'person-uuid-2', name: 'Bob' });
const carol = rosterPerson({ id: 3, person_uuid: 'person-uuid-3', name: 'Carol' });

const emptyPage = {
  media: [],
  limit: 50,
  offset: 0,
  total: 0,
  truncated: false,
};

const photoPage = {
  media: [
    {
      identity_id: 'identity-1',
      media_id: 501,
      media_url: 'https://example.com/photo-501.jpg',
      bbox: { x: 10, y: 20, width: 30, height: 40 },
      similarity: 0.9,
      cluster_id: CLUSTER_UUID,
    },
  ],
  limit: 50,
  offset: 0,
  total: 1,
  truncated: false,
};

const Providers = ({ children }: { children: React.ReactNode }): React.JSX.Element => {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      }),
  );
  return (
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MemoryRouter>
  );
};

const renderPanel = (ui: React.ReactElement) => render(ui, { wrapper: Providers });

const mediaRequestUrl = (): URL => {
  const mediaCalls = vi
    .mocked(fetchRequiredApi)
    .mock.calls.map((call) => String(call[0] ?? ''))
    .filter((url) => url.includes('/media'));
  const mediaCall = mediaCalls[mediaCalls.length - 1];
  expect(mediaCall).toBeDefined();
  return new URL(mediaCall ?? '', 'http://example.test');
};

const configureEndpoints = (): void => {
  window.AltContextAdmin = {
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      rosterPersons: 'http://example.test/wp-json/acx/v1/roster/persons',
      rosterEntries: 'http://example.test/wp-json/acx/v1/roster/entries',
    },
  };
  resetConfigCache();
};

beforeEach(() => {
  delete window.AltContextAdmin;
  resetConfigCache();
  vi.mocked(fetchRequiredApi).mockReset();
  vi.mocked(fetchRequiredApi).mockResolvedValue(emptyPage);
  vi.mocked(listRosterEntries).mockReset();
  vi.mocked(listRosterEntries).mockResolvedValue([alice, bob, carol]);
  configureEndpoints();
});

afterEach(() => {
  delete window.AltContextAdmin;
  resetConfigCache();
  cleanup();
});

const selectAlsoWith = async (name: string): Promise<void> => {
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox', { name: /Also with/ }));
  await user.click(await screen.findByRole('option', { name }));
};

describe('PersonWorkspacePanel Also with filter', () => {
  it('keeps Also with in the Photos chrome and leaves unfiltered empty copy generic', async () => {
    renderPanel(<PersonWorkspacePanel entry={alice} onOpenQueue={vi.fn()} />);

    const photos = await screen.findByRole('region', { name: 'Photos' });
    expect(within(photos).getByRole('combobox', { name: /Also with/ })).toBeInTheDocument();
    expect(within(photos).getByText('No photos of this person yet.')).toBeInTheDocument();
    expect(within(photos).queryByText(/No photos of Alice also with/)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mediaRequestUrl().searchParams.getAll('with_person_ids[]')).toEqual([]);
    });
  });

  it('feeds with_person_ids[] from named people and shows removable chips', async () => {
    vi.mocked(fetchRequiredApi).mockResolvedValue(photoPage);

    renderPanel(<PersonWorkspacePanel entry={alice} onOpenQueue={vi.fn()} />);
    await screen.findByRole('region', { name: 'Photos' });
    await selectAlsoWith('Bob');

    expect(await screen.findByRole('button', { name: 'Remove Bob' })).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();

    await waitFor(() => {
      expect(mediaRequestUrl().searchParams.getAll('with_person_ids[]')).toEqual(['2']);
    });
  });

  it('names the people searched when the filtered photo grid is empty', async () => {
    renderPanel(<PersonWorkspacePanel entry={alice} onOpenQueue={vi.fn()} />);
    await screen.findByText('No photos of this person yet.');
    await selectAlsoWith('Bob');
    await selectAlsoWith('Carol');

    expect(await screen.findByText('No photos of Alice also with Bob and Carol.')).toBeInTheDocument();
    expect(screen.queryByText('No photos of this person yet.')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mediaRequestUrl().searchParams.getAll('with_person_ids[]')).toEqual(['2', '3']);
    });
  });

  it('drops a person from the photo query when their chip is removed', async () => {
    const user = userEvent.setup();
    renderPanel(<PersonWorkspacePanel entry={alice} onOpenQueue={vi.fn()} />);
    await screen.findByRole('region', { name: 'Photos' });
    await selectAlsoWith('Bob');

    await waitFor(() => {
      expect(mediaRequestUrl().searchParams.getAll('with_person_ids[]')).toEqual(['2']);
    });

    await user.click(screen.getByRole('button', { name: 'Remove Bob' }));

    expect(screen.queryByRole('button', { name: 'Remove Bob' })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mediaRequestUrl().searchParams.getAll('with_person_ids[]')).toEqual([]);
    });
    expect(await screen.findByText('No photos of this person yet.')).toBeInTheDocument();
  });

  it('does not offer the current person as an Also with option', async () => {
    const user = userEvent.setup();
    renderPanel(<PersonWorkspacePanel entry={alice} onOpenQueue={vi.fn()} />);
    await screen.findByRole('region', { name: 'Photos' });
    await user.click(screen.getByRole('combobox', { name: /Also with/ }));

    expect(await screen.findByRole('option', { name: 'Bob' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Carol' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Alice' })).not.toBeInTheDocument();
  });

  it('caps Also with selection at five people', async () => {
    const extras = [4, 5, 6, 7].map((id) =>
      rosterPerson({ id, person_uuid: `person-uuid-${id}`, name: `Person ${id}` }),
    );
    vi.mocked(listRosterEntries).mockResolvedValue([alice, bob, carol, ...extras]);

    renderPanel(<PersonWorkspacePanel entry={alice} onOpenQueue={vi.fn()} />);
    await screen.findByRole('region', { name: 'Photos' });
    await selectAlsoWith('Bob');
    await selectAlsoWith('Carol');
    await selectAlsoWith('Person 4');
    await selectAlsoWith('Person 5');
    await selectAlsoWith('Person 6');

    expect(screen.getByRole('button', { name: 'Remove Person 6' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Also with/ })).toBeDisabled();
    await waitFor(() => {
      expect(mediaRequestUrl().searchParams.getAll('with_person_ids[]')).toEqual(['2', '3', '4', '5', '6']);
    });
  });

  it('clears Also with chips when the person identity changes', async () => {
    const { rerender } = renderPanel(<PersonWorkspacePanel entry={alice} onOpenQueue={vi.fn()} />);
    await screen.findByRole('region', { name: 'Photos' });
    await selectAlsoWith('Bob');
    expect(await screen.findByRole('button', { name: 'Remove Bob' })).toBeInTheDocument();

    rerender(<PersonWorkspacePanel entry={bob} onOpenQueue={vi.fn()} />);

    expect(screen.queryByRole('button', { name: 'Remove Bob' })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mediaRequestUrl().searchParams.getAll('with_person_ids[]')).toEqual([]);
    });
  });
});

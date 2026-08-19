import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { listRosterEntries } from '../../../../api/rosterApi';
import { LightboxNameFace } from '../LightboxNameFace';
import { PERSON_COMMIT_COMBOBOX_ARIA } from '../personCommitCopy';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

vi.mock('../../../../api/rosterApi', () => ({
  listRosterEntries: vi.fn(),
}));

const rosterEntry = (id: number, name: string) => ({
  id,
  person_uuid: `person-uuid-${id}`,
  name,
  tags: [],
  cluster_count: 0,
  clusters: [],
  queue_memberships: [],
  updated_at: new Date().toISOString(),
  source_version: 1,
  projection_status: 'current' as const,
  projection_refreshed_at: new Date().toISOString(),
});

const renderNaming = (
  overrides: Partial<React.ComponentProps<typeof LightboxNameFace>> = {},
  roster: ReturnType<typeof rosterEntry>[] = [],
) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClient.setQueryData(queryKeys.roster.entries(), roster);
  const onCommit = vi.fn();
  const onCancel = vi.fn();
  const props: React.ComponentProps<typeof LightboxNameFace> = {
    clusterId: 'cluster-1',
    runSize: 3,
    phase: 'idle',
    errorMessage: null,
    onCommit,
    onCancel,
    onRetry: vi.fn(),
    ...overrides,
  };
  render(
    <QueryClientProvider client={queryClient}>
      <LightboxNameFace {...props} />
    </QueryClientProvider>,
  );
  return { onCommit, onCancel, queryClient };
};

describe('LightboxNameFace (UXW2-6 slice 2)', () => {
  beforeEach(() => {
    vi.mocked(listRosterEntries).mockResolvedValue([]);
  });

  it('commits a novel name through newEntryName for the cluster', async () => {
    const { onCommit } = renderNaming();
    const user = userEvent.setup();

    const input = await screen.findByRole('combobox', { name: PERSON_COMMIT_COMBOBOX_ARIA });
    await user.type(input, 'Pat Rivera{Enter}');

    expect(onCommit).toHaveBeenCalledWith({ clusterId: 'cluster-1', newEntryName: 'Pat Rivera' });
  });

  it('binds an exact roster match to rosterEntryId', async () => {
    const { onCommit } = renderNaming({}, [rosterEntry(7, 'Alex')]);
    const user = userEvent.setup();

    const input = await screen.findByRole('combobox', { name: PERSON_COMMIT_COMBOBOX_ARIA });
    await user.type(input, 'Alex{Enter}');

    await waitFor(() => {
      expect(onCommit).toHaveBeenCalledWith({ clusterId: 'cluster-1', rosterEntryId: 7 });
    });
  });

  it('shows an explicit truncation signal when the group is larger than 25', () => {
    renderNaming({ runSize: 40 });

    expect(
      screen.getByText('Naming the first 25 faces in this group. 15 more were not included.'),
    ).toBeInTheDocument();
  });

  it('does not show truncation when the group fits in the cap', () => {
    renderNaming({ runSize: 3 });

    expect(screen.queryByText(/were not included/)).not.toBeInTheDocument();
  });
});

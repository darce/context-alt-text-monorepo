import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listRosterEntries } from '../../../../api/rosterApi';
import { PersonCommitControl } from '../PersonCommitControl';
import { PERSON_COMMIT_CONFIRM_COPY } from '../personCommitCopy';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

vi.mock('../../../../api/rosterApi', () => ({
  listRosterEntries: vi.fn(),
}));

const RESERVED_MESSAGE =
  'This label format is reserved for automatic cluster IDs. Choose a descriptive name.';

const renderControl = (
  overrides: Partial<React.ComponentProps<typeof PersonCommitControl>> = {},
) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onCommit = vi.fn();
  const props: React.ComponentProps<typeof PersonCommitControl> = {
    clusterId: 'cluster-1',
    phase: 'idle',
    errorMessage: null,
    onCommit,
    onRetry: vi.fn(),
    ...overrides,
  };
  render(
    <QueryClientProvider client={queryClient}>
      <PersonCommitControl {...props} />
    </QueryClientProvider>,
  );
  return { onCommit };
};

describe('PersonCommitControl reserved create-name gate (BR-59)', () => {
  beforeEach(() => {
    vi.mocked(listRosterEntries).mockResolvedValue([]);
  });

  it('create-entry name cluster-7 rejects without onCommit and shows reserved message', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: 'cluster-7' });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
  });

  it('create-entry name Pat Rivera proceeds to onCommit (control)', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: 'Pat Rivera' });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      newEntryName: 'Pat Rivera',
    });
    expect(screen.queryByText(RESERVED_MESSAGE)).not.toBeInTheDocument();
  });

  it('select-existing entry commits without reserved blocking', async () => {
    vi.mocked(listRosterEntries).mockResolvedValue([
      {
        id: 42,
        person_uuid: 'person-uuid-alex',
        name: 'Alex Carter',
        tags: [],
        cluster_count: 0,
        clusters: [],
        queue_memberships: [],
        updated_at: new Date().toISOString(),
        source_version: 1,
        projection_status: 'current',
        projection_refreshed_at: new Date().toISOString(),
      },
    ]);
    const { onCommit } = renderControl();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('combobox', { name: /Commit to roster entry/i }));
    await user.click(await screen.findByRole('option', { name: 'Alex Carter' }));
    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      rosterEntryId: 42,
    });
    expect(screen.queryByText(RESERVED_MESSAGE)).not.toBeInTheDocument();
  });

  it('reserved error clears when switching to an existing entry after reject', async () => {
    vi.mocked(listRosterEntries).mockResolvedValue([
      {
        id: 42,
        person_uuid: 'person-uuid-alex',
        name: 'Alex Carter',
        tags: [],
        cluster_count: 0,
        clusters: [],
        queue_memberships: [],
        updated_at: new Date().toISOString(),
        source_version: 1,
        projection_status: 'current',
        projection_refreshed_at: new Date().toISOString(),
      },
    ]);
    const { onCommit } = renderControl({ suggestedCreateName: 'cluster-7' });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
    expect(onCommit).not.toHaveBeenCalled();

    await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
    await user.click(await screen.findByRole('option', { name: 'Alex Carter' }));

    expect(screen.queryByText(RESERVED_MESSAGE)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));
    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      rosterEntryId: 42,
    });
  });

  it('create name is trimmed before the reserved gate', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: '  cluster-7  ' });
    const user = userEvent.setup();

    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
  });
});

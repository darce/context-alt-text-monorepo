import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
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

const INPUT_NAME = 'Name this person';

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

describe('PersonCommitControl single-gesture naming (UXW2-3)', () => {
  beforeEach(() => {
    vi.mocked(listRosterEntries).mockResolvedValue([]);
  });

  it('typing a novel name + Enter commits with newEntryName (create is the default)', async () => {
    const { onCommit } = renderControl();
    const user = userEvent.setup();

    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    await user.type(input, 'Pat Rivera{Enter}');

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      newEntryName: 'Pat Rivera',
    });
  });

  it('typing an existing roster name + Enter commits with rosterEntryId', async () => {
    vi.mocked(listRosterEntries).mockResolvedValue([rosterEntry(42, 'Alex Carter')]);
    const { onCommit } = renderControl();
    const user = userEvent.setup();

    // Wait for the roster typeahead to load before typing.
    await screen.findByText('Alex Carter');
    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    await user.type(input, 'Alex Carter{Enter}');

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      rosterEntryId: 42,
    });
  });

  it('exact roster match is case-insensitive and trims whitespace', async () => {
    vi.mocked(listRosterEntries).mockResolvedValue([rosterEntry(42, 'Alex Carter')]);
    const { onCommit } = renderControl();
    const user = userEvent.setup();

    await screen.findByText('Alex Carter');
    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    await user.type(input, '  alex carter {Enter}');

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      rosterEntryId: 42,
    });
  });

  it('Save name button commits a novel name', async () => {
    const { onCommit } = renderControl();
    const user = userEvent.setup();

    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    await user.type(input, 'Pat Rivera');
    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      newEntryName: 'Pat Rivera',
    });
  });

  it('renders an inline text input, not a popover trigger', () => {
    renderControl();

    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    expect(input.tagName).toBe('INPUT');
  });

  it('no "Just label" tertiary control is present', () => {
    renderControl();

    expect(
      screen.queryByRole('button', { name: /just label/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/don't add to roster/i)).not.toBeInTheDocument();
  });

  it('prefills a suggested create name and Enter commits it', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: 'Pat Rivera' });
    const user = userEvent.setup();

    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    await waitFor(() => expect(input).toHaveValue('Pat Rivera'));
    await user.type(input, '{Enter}');

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      newEntryName: 'Pat Rivera',
    });
  });
});

describe('PersonCommitControl reserved create-name gate (BR-59)', () => {
  beforeEach(() => {
    vi.mocked(listRosterEntries).mockResolvedValue([]);
  });

  it('reserved name cluster-7 rejects without onCommit and shows reserved message', async () => {
    const { onCommit } = renderControl();
    const user = userEvent.setup();

    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    await user.type(input, 'cluster-7{Enter}');

    expect(onCommit).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
  });

  it('reserved name via Save name button rejects', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: 'cluster-7' });
    const user = userEvent.setup();

    await screen.findByRole('combobox', { name: INPUT_NAME });
    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
  });

  it('create name is trimmed before the reserved gate', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: '  cluster-7  ' });
    const user = userEvent.setup();

    await screen.findByRole('combobox', { name: INPUT_NAME });
    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
  });

  it('valid name Pat Rivera proceeds to onCommit (control)', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: 'Pat Rivera' });
    const user = userEvent.setup();

    await screen.findByRole('combobox', { name: INPUT_NAME });
    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      newEntryName: 'Pat Rivera',
    });
    expect(screen.queryByText(RESERVED_MESSAGE)).not.toBeInTheDocument();
  });

  it('reserved error clears when the draft is edited after a reject', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: 'cluster-7' });
    const user = userEvent.setup();

    const input = await screen.findByRole('combobox', { name: INPUT_NAME });
    await user.click(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY }));
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);

    await user.clear(input);
    await user.type(input, 'Pat Rivera{Enter}');

    expect(screen.queryByText(RESERVED_MESSAGE)).not.toBeInTheDocument();
    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      newEntryName: 'Pat Rivera',
    });
  });
});

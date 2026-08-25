import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { listRosterEntries } from '../../../../api/rosterApi';
import { PersonCommitControl } from '../PersonCommitControl';
import { MODEL_OUTPUT_DISCLOSURE } from '../personCommitCopy';

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

const RESERVED_MESSAGE =
  'This label format is reserved for automatic group IDs. Choose a descriptive name.';

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
  roster: ReturnType<typeof rosterEntry>[] = [],
) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClient.setQueryData(queryKeys.roster.entries(), roster);
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
  return { onCommit, queryClient };
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
    const { onCommit } = renderControl({}, [rosterEntry(42, 'Alex Carter')]);
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
    const { onCommit } = renderControl({}, [rosterEntry(42, 'Alex Carter')]);
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
    await user.click(screen.getByRole('button', { name: 'Create person "Pat Rivera"' }));

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

  it('the name input has a visible associated label (UXW2-3-R3-26)', () => {
    renderControl();
    expect(screen.getByLabelText('Name this person')).toBe(screen.getByRole('combobox'));
    expect(screen.getByText('Name this person').tagName).toBe('LABEL');
  });

  it('takes the accessible name from the visible label, not aria-label (UXW2-3-R6-08)', () => {
    renderControl();
    const input = screen.getByRole('combobox');
    expect(input).toHaveAccessibleName('Name this person');
    expect(screen.getByLabelText('Name this person')).toBe(input);
    const label = screen.getByText('Name this person');
    expect(label.tagName).toBe('LABEL');
    expect(label).toHaveAttribute('for', input.id);
    expect(input).not.toHaveAttribute('aria-label');
  });

  it('no "Just label" tertiary control is present', () => {
    renderControl();

    expect(
      screen.queryByRole('button', { name: /just label/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/don't add to roster/i)).not.toBeInTheDocument();
  });

  it('offers a curate-group control that reports the cluster id (UXW2-3-R3-01)', async () => {
    const onCurateGroup = vi.fn();
    renderControl({ onCurateGroup });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Merge or split this group' }));
    expect(onCurateGroup).toHaveBeenCalledWith('cluster-1');
  });

  it('renders the model-output disclosure when suggestedCreateName is present (UXW2-3-R6-05)', () => {
    renderControl({ suggestedCreateName: 'Morgan' });
    expect(screen.getByText(MODEL_OUTPUT_DISCLOSURE)).toBeInTheDocument();
  });

  it('does not render the model-output disclosure when suggestedCreateName is null (UXW2-3-R6-05)', () => {
    renderControl({ suggestedCreateName: null });
    expect(screen.queryByText(MODEL_OUTPUT_DISCLOSURE)).not.toBeInTheDocument();
  });

  it('clicking Confirm match on a visible roster row binds rosterEntryId (UXW2-3-R1-08b)', async () => {
    const { onCommit } = renderControl({}, [rosterEntry(42, 'Alex Carter')]);
    const user = userEvent.setup();

    const option = await screen.findByRole('option', { name: /Confirm match with Alex Carter/ });
    await user.click(option);

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      rosterEntryId: 42,
    });
    expect(onCommit).not.toHaveBeenCalledWith(
      expect.objectContaining({ newEntryName: expect.anything() }),
    );
  });

  it('prefill that matches a roster entry + Enter binds rosterEntryId, not a create (UXW2-3-R1-08b)', async () => {
    const { onCommit } = renderControl(
      { suggestedCreateName: 'Alex Carter' },
      [rosterEntry(42, 'Alex Carter')],
    );
    const user = userEvent.setup();

    const input = screen.getByRole('combobox', { name: INPUT_NAME });
    await waitFor(() => expect(input).toHaveValue('Alex Carter'));
    await screen.findByRole('option', { name: /Alex Carter/ });
    await user.type(input, '{Enter}');

    expect(onCommit).toHaveBeenCalledWith({
      clusterId: 'cluster-1',
      rosterEntryId: 42,
    });
    expect(onCommit).not.toHaveBeenCalledWith(
      expect.objectContaining({ newEntryName: expect.anything() }),
    );
  });

  it('overlay header is People on a roster-only list (UXW2-3-R1-16b)', async () => {
    renderControl({}, [rosterEntry(42, 'Alex Carter')]);
    await screen.findByRole('option', { name: /Alex Carter/ });
    expect(screen.getByText('People')).toBeInTheDocument();
    expect(screen.queryByText('Suggested')).not.toBeInTheDocument();
  });

  it('omits whitespace-only roster names via buildNamingOptions (UXW2-3-R1-07)', async () => {
    renderControl({}, [rosterEntry(42, 'Alex Carter'), rosterEntry(7, '   ')]);
    await screen.findByRole('option', { name: /Alex Carter/ });
    expect(screen.getAllByRole('option')).toHaveLength(1);
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
    await user.click(screen.getByRole('button', { name: 'Create person "cluster-7"' }));

    expect(onCommit).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
  });

  it('create name is trimmed before the reserved gate', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: '  cluster-7  ' });
    const user = userEvent.setup();

    await screen.findByRole('combobox', { name: INPUT_NAME });
    await user.click(screen.getByRole('button', { name: 'Create person "cluster-7"' }));

    expect(onCommit).not.toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent(RESERVED_MESSAGE);
  });

  it('valid name Pat Rivera proceeds to onCommit (control)', async () => {
    const { onCommit } = renderControl({ suggestedCreateName: 'Pat Rivera' });
    const user = userEvent.setup();

    await screen.findByRole('combobox', { name: INPUT_NAME });
    await user.click(screen.getByRole('button', { name: 'Create person "Pat Rivera"' }));

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
    await user.click(screen.getByRole('button', { name: 'Create person "cluster-7"' }));
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

describe('PersonCommitControl roster query states (UXW2-3-R1-02)', () => {
  it('loading people disables the create path and announces', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.mocked(listRosterEntries).mockReturnValue(new Promise(() => undefined));
    render(
      <QueryClientProvider client={queryClient}>
        <PersonCommitControl
          clusterId="cluster-1"
          phase="idle"
          errorMessage={null}
          onCommit={vi.fn()}
          onRetry={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByRole('status')).toHaveTextContent('Loading people…');
    expect(screen.getByRole('combobox', { name: INPUT_NAME })).toBeDisabled();
  });

  it('roster error blocks create and offers retry', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.mocked(listRosterEntries).mockRejectedValue(new Error('boom'));
    render(
      <QueryClientProvider client={queryClient}>
        <PersonCommitControl
          clusterId="cluster-1"
          phase="idle"
          errorMessage={null}
          onCommit={vi.fn()}
          onRetry={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('alert')).toHaveTextContent(/Unable to load people/);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('invalidates the roster query key when commit succeeds', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    queryClient.setQueryData(queryKeys.roster.entries(), []);
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    render(
      <QueryClientProvider client={queryClient}>
        <PersonCommitControl
          clusterId="cluster-1"
          phase="succeeded"
          errorMessage={null}
          onCommit={vi.fn()}
          onRetry={vi.fn()}
          committedPersonUuid="person-uuid-42"
        />
      </QueryClientProvider>,
    );

    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.roster.entries() });
    expect(screen.getByRole('link', { name: /View in roster/ })).toHaveAttribute(
      'href',
      '#/roster?person=person-uuid-42',
    );
  });

  it('W3-C-14 accentPrimary=true renders accent chrome on secondary name-commit', () => {
    renderControl({ isPrimary: true, accentPrimary: true });
    const save = screen.getByRole('button', { name: 'Save name' });
    expect(save).toHaveClass('button-secondary');
    expect(save).toHaveClass('acx-accent-primary-action');
    expect(save).not.toHaveClass('button-primary');
  });

  it('W3-C-14 accentPrimary=false renders no accent and no button-primary', () => {
    renderControl({ isPrimary: true, accentPrimary: false });
    const save = screen.getByRole('button', { name: 'Save name' });
    expect(save).toHaveClass('button-secondary');
    expect(save).not.toHaveClass('acx-accent-primary-action');
    expect(save).not.toHaveClass('button-primary');
  });
});

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { useDeletePerson, useUpdatePerson } from '../../../hooks/useRosterHooks';
import { createMockMutation } from '../../../test-utils/mockHooks';
import { RosterEntriesTable } from '../RosterEntriesTable';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

vi.mock('../../../hooks/useRosterHooks', () => ({
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));

const RESERVED_LABEL_MESSAGE =
  'This name format is reserved for automatic face group IDs. Choose a descriptive name.';

const makeEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: 'person-uuid-alice',
  name: 'Alice Anderson',
  tags: ['family'],
  cluster_count: 0,
  clusters: [],
  queue_memberships: [],
  updated_at: new Date().toISOString(),
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: new Date().toISOString(),
  ...overrides,
});

const updateMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const deleteMutation = createMockMutation({ mutate: vi.fn(), isPending: false });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation as never);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation as never);
});

describe('RosterEntriesTable rename reserved-label gate (BR-60)', () => {
  it('rejects cluster-7 without calling updatePerson and shows reserved message', async () => {
    const user = userEvent.setup();
    render(<RosterEntriesTable entries={[makeEntry()]} />);

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    const nameInput = screen.getByDisplayValue('Alice Anderson');
    await user.clear(nameInput);
    await user.type(nameInput, 'cluster-7');
    await user.click(screen.getByRole('button', { name: /Save changes/i }));

    expect(updateMutation.mutate).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(RESERVED_LABEL_MESSAGE);
  });

  it('saves Pat Rivera via updatePerson (human-label control)', async () => {
    const user = userEvent.setup();
    render(<RosterEntriesTable entries={[makeEntry()]} />);

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    const nameInput = screen.getByDisplayValue('Alice Anderson');
    await user.clear(nameInput);
    await user.type(nameInput, 'Pat Rivera');
    await user.click(screen.getByRole('button', { name: /Save changes/i }));

    expect(updateMutation.mutate).toHaveBeenCalledTimes(1);
    expect(updateMutation.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, name: 'Pat Rivera' }),
      expect.any(Object),
    );
    expect(screen.queryByText(RESERVED_LABEL_MESSAGE)).not.toBeInTheDocument();
  });
});

describe('RosterEntriesTable legacy reserved name save gate (BR-63)', () => {
  it('allows tag-only save when existing name is unchanged cluster-7', async () => {
    const user = userEvent.setup();
    render(
      <RosterEntriesTable
        entries={[makeEntry({ name: 'cluster-7', tags: ['family'] })]}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    expect(screen.getByDisplayValue('cluster-7')).toBeInTheDocument();
    const tagsInput = screen.getByDisplayValue('family');
    await user.clear(tagsInput);
    await user.type(tagsInput, 'vip, alumni');
    await user.click(screen.getByRole('button', { name: /Save changes/i }));

    expect(updateMutation.mutate).toHaveBeenCalledTimes(1);
    expect(updateMutation.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 1,
        name: 'cluster-7',
        tags: ['vip', 'alumni'],
      }),
      expect.any(Object),
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(RESERVED_LABEL_MESSAGE)).not.toBeInTheDocument();
  });

  it('rejects rename from cluster-7 to a different reserved value cluster-9', async () => {
    const user = userEvent.setup();
    render(
      <RosterEntriesTable entries={[makeEntry({ name: 'cluster-7' })]} />,
    );

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    const nameInput = screen.getByDisplayValue('cluster-7');
    await user.clear(nameInput);
    await user.type(nameInput, 'cluster-9');
    await user.click(screen.getByRole('button', { name: /Save changes/i }));

    expect(updateMutation.mutate).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(RESERVED_LABEL_MESSAGE);
  });
});

describe('RosterEntriesTable trim-normalization pin (BR-67)', () => {
  it('allows tag-only save when backend name has trailing padding (cluster-7 )', async () => {
    const user = userEvent.setup();
    render(
      <RosterEntriesTable
        entries={[makeEntry({ name: 'cluster-7 ', tags: ['family'] })]}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    const [nameInput, tagsInput] = screen.getAllByRole<HTMLInputElement>('textbox');
    // getByDisplayValue collapses trailing whitespace; assert the raw padded value.
    expect(nameInput).toHaveValue('cluster-7 ');
    expect(nameInput.value.trim()).toBe('cluster-7');
    await user.clear(tagsInput);
    await user.type(tagsInput, 'vip, alumni');
    await user.click(screen.getByRole('button', { name: /Save changes/i }));

    expect(updateMutation.mutate).toHaveBeenCalledTimes(1);
    expect(updateMutation.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 1,
        name: 'cluster-7',
        tags: ['vip', 'alumni'],
      }),
      expect.any(Object),
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(RESERVED_LABEL_MESSAGE)).not.toBeInTheDocument();
  });
});

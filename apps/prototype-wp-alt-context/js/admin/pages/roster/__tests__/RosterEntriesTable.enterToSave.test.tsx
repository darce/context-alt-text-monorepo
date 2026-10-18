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

describe('RosterEntriesTable keyboard edit controls', () => {
  it('saves the row when Enter is pressed in the name input', async () => {
    const user = userEvent.setup();
    render(<RosterEntriesTable entries={[makeEntry()]} />);

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    await user.keyboard('{Enter}');

    expect(updateMutation.mutate).toHaveBeenCalledTimes(1);
    expect(updateMutation.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 1, name: 'Alice Anderson' }),
      expect.any(Object),
    );
  });

  it('cancels the row when Escape is pressed in the tags input', async () => {
    const user = userEvent.setup();
    render(<RosterEntriesTable entries={[makeEntry()]} />);

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    const tagsInput = screen.getByRole('textbox', { name: 'Tags' });
    await user.clear(tagsInput);
    await user.type(tagsInput, 'vip');
    await user.keyboard('{Escape}');

    expect(updateMutation.mutate).not.toHaveBeenCalled();
    expect(screen.queryByRole('textbox', { name: 'Tags' })).not.toBeInTheDocument();
    expect(screen.getByText('family')).toBeInTheDocument();
  });

  it('does not save on Enter when the name is empty', async () => {
    const user = userEvent.setup();
    render(<RosterEntriesTable entries={[makeEntry()]} />);

    await user.click(screen.getByRole('button', { name: /Edit person/i }));
    const nameInput = screen.getByRole('textbox', { name: 'Person name' });
    await user.clear(nameInput);
    await user.keyboard('{Enter}');

    expect(updateMutation.mutate).not.toHaveBeenCalled();
    expect(nameInput).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save changes to Alice Anderson' })).toBeDisabled();
  });

  it('gives Save and Cancel buttons accessible names that include the person name', async () => {
    const user = userEvent.setup();
    render(<RosterEntriesTable entries={[makeEntry()]} />);

    await user.click(screen.getByRole('button', { name: /Edit person/i }));

    expect(screen.getByRole('button', { name: 'Save changes to Alice Anderson' })).toHaveAccessibleName(
      'Save changes to Alice Anderson',
    );
    expect(screen.getByRole('button', { name: 'Cancel editing Alice Anderson' })).toHaveAccessibleName(
      'Cancel editing Alice Anderson',
    );
  });
});

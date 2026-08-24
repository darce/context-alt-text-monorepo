import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../../hooks/useRosterHooks';
import { createMockMutation } from '../../../test-utils/mockHooks';
import { RosterEntriesSection } from '../RosterEntriesSection';

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
  useCreatePerson: vi.fn(),
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));

const entry: RosterEntry = {
  id: 7,
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
};

const createMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const updateMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const deleteMutation = createMockMutation({ mutate: vi.fn(), isPending: false });

const renderSection = () =>
  render(
    <MemoryRouter initialEntries={['/?tab=entries']}>
      <RosterEntriesSection
        query={{
          isLoading: false,
          isError: false,
          data: [entry],
          refetch: vi.fn(),
        }}
      />
    </MemoryRouter>,
  );

const expectVisibleLabelBinding = (input: HTMLElement, labelText: string) => {
  const label = screen.getByText(labelText, { selector: 'label' });
  expect(label).toBeVisible();
  expect(input).toHaveAttribute('id');
  expect(label).toHaveAttribute('for', input.id);
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCreatePerson).mockReturnValue(createMutation as never);
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation as never);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation as never);
});

describe('RosterEntriesSection visible field labels [UXB-02][A11Y-03]', () => {
  it('binds a visible Full name label to the create field', async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole('button', { name: /add person/i }));

    expectVisibleLabelBinding(screen.getByRole('textbox', { name: 'Full name' }), 'Full name');
  });

  it('binds a visible Person name label to the edit name field', async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole('button', { name: /edit person/i }));

    expectVisibleLabelBinding(screen.getByRole('textbox', { name: 'Person name' }), 'Person name');
  });

  it('binds a visible Tags label to the edit tags field', async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole('button', { name: /edit person/i }));

    expectVisibleLabelBinding(screen.getByRole('textbox', { name: 'Tags' }), 'Tags');
  });
});

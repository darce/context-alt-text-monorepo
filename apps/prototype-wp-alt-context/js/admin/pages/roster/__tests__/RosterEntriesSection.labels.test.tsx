import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../../hooks/useRosterHooks';
import { createMockMutation } from '../../../test-utils/mockHooks';
import { RosterEntriesSection, type RosterEntriesQuery } from '../RosterEntriesSection';

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
  id: 42,
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

const query: RosterEntriesQuery = {
  isLoading: false,
  isError: false,
  data: [entry],
  refetch: vi.fn(),
};

const createMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const updateMutation = createMockMutation({ mutate: vi.fn(), isPending: false });
const deleteMutation = createMockMutation({ mutate: vi.fn(), isPending: false });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCreatePerson).mockReturnValue(createMutation as never);
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation as never);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation as never);
});

const expectVisibleHtmlLabel = (control: HTMLElement, labelText: string) => {
  const label = screen.getByText(labelText, { selector: 'label' });
  expect(label).toBeVisible();
  expect(control).toHaveAttribute('id');
  expect(label).toHaveAttribute('for', control.id);
};

describe('roster input labels [A11Y-03]', () => {
  it('associates visible labels with every create-form and edit-row input', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <RosterEntriesSection query={query} />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole('button', { name: 'Add Person' }));
    const createForm = document.querySelector('.acx-roster-section__add-form');
    expect(createForm).not.toBeNull();
    const createName = within(createForm!).getByRole('textbox', { name: 'Full name' });
    expectVisibleHtmlLabel(createName, 'Full name');

    await user.click(screen.getByRole('button', { name: 'Edit person' }));
    const editRow = screen.getByRole('button', { name: 'Save changes' }).closest('tr');
    expect(editRow).not.toBeNull();
    const editName = within(editRow!).getByRole('textbox', { name: 'Name' });
    const editTags = within(editRow!).getByRole('textbox', { name: 'Tags' });
    expectVisibleHtmlLabel(editName, 'Name');
    expectVisibleHtmlLabel(editTags, 'Tags');
  });
});

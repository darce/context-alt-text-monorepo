import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RosterEntry } from '../../../api/rosterApi';
import { RosterEntriesTable } from '../RosterEntriesTable';
import { PersonWorkspacePanel } from '../PersonWorkspacePanel';

vi.mock('../../../hooks/useRosterHooks', () => ({
  useUpdatePerson: () => ({ mutate: vi.fn(), isPending: false }),
  useDeletePerson: () => ({ mutate: vi.fn(), isPending: false }),
}));

const entry: RosterEntry = {
  id: 42, person_uuid: 'stable-person-a', name: 'Example Person', tags: [],
  cluster_count: 3, queue_memberships: [], updated_at: '2026-10-24T00:00:00Z',
  source_version: 1, projection_status: 'current', projection_refreshed_at: '2026-10-24T00:00:00Z',
  clusters: [{cluster_id: 'group-a', identity_count: 1,
    representative_identity: { identity_id: 'face-a', media_id: 101,
      media_url: '/fixture.jpg', bbox: null, similarity: null }, instances: []}],
};
const Location = () => <output data-testid="route">{useLocation().search}{useLocation().hash}</output>;
const renderTable = (person: RosterEntry = entry) => render(
  <MemoryRouter initialEntries={['/roster?s=Example&queue=hard-examples&face=old&cluster=old&tab=entries']}>
    <RosterEntriesTable entries={[person]} onOpenPerson={vi.fn()} /><Location />
  </MemoryRouter>,
);
const renderPanel = (hash = '') => render(
  <MemoryRouter initialEntries={[`/roster?person=${entry.person_uuid}${hash}`]}>
    <QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
      <PersonWorkspacePanel entry={entry} onOpenQueue={vi.fn()} />
    </QueryClientProvider>
  </MemoryRouter>,
);
afterEach(() => { vi.restoreAllMocks(); });

describe('ROSTER_EVIDENCE collection discovery', () => {
  it('keeps the directory evidence legible at 64px, including the broken-image fallback', () => {
    renderTable();
    const image = within(screen.getByRole('button', {name:entry.name})).getByRole('presentation');
    expect(image).toHaveAttribute('width', '64');
    fireEvent.error(image);
    const fallback = screen.getByRole('button', {name:entry.name}).querySelector('[data-face-missing]');
    expect(fallback).toHaveStyle({width:'64px',height:'64px'});
  });

  it('exposes View photos as a stable-person deep link without calling face groups photos', async () => {
    const user = userEvent.setup(); renderTable();
    const link = screen.getByRole('link', {name:'View photos for Example Person'});
    expect(link).toHaveTextContent('View photos');
    await user.click(link);
    const route = screen.getByTestId('route').textContent ?? '';
    const params = new URLSearchParams(route);
    expect(params.get('person')).toBe(entry.person_uuid);
    expect(params.get('queue')).toBe('hard-examples');
    expect(params.get('s')).toBe('Example');
    expect(params.get('section')).toBe('photos');
    for (const key of ['face','cluster','tab']) expect(params.has(key)).toBe(false);
    expect(screen.getByRole('columnheader', {name:'Face groups'})).toBeInTheDocument();
    expect(screen.queryByText('3 photos')).not.toBeInTheDocument();
  });

  it('does not offer collection navigation without a resolved stable person UUID', () => {
    renderTable({...entry,person_uuid:''});
    expect(screen.queryByRole('link', {name:/View photos/})).not.toBeInTheDocument();
  });

  it('shows 96px representative evidence beside the person header', () => {
    renderPanel();
    const header = screen.getByRole('heading', {name:entry.name,level:3}).closest('header')!;
    expect(within(header).getByRole('presentation')).toHaveAttribute('width','96');
    expect(within(header).getByRole('link', {name:'View photos'})).toBeInTheDocument();
  });

  it('restores the existing Photos section as the keyboard focus destination from the URL', () => {
    const scroll = vi.spyOn(HTMLElement.prototype,'scrollIntoView').mockReturnValue(undefined);
    renderPanel('&section=photos');
    expect(screen.getByRole('region', {name:'Photos'})).toHaveFocus();
    expect(scroll).toHaveBeenCalled();
  });
});

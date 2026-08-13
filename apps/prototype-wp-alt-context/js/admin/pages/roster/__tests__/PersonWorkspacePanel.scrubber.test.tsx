import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { pinRepresentative } from '../../../api/recognition/clusterApiMutations';
import { PersonWorkspacePanel } from '../PersonWorkspacePanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: Array<string | number>) => {
    let index = 0;
    return format.replace(/%[sd]/g, () => String(args[index++]));
  },
}));

vi.mock('../../../api/recognition/clusterApiMutations', () => ({
  pinRepresentative: vi.fn(),
}));

const CLUSTER_UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

const baseEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: 'person-uuid-1',
  name: 'Alice',
  tags: [],
  cluster_count: 1,
  clusters: [
    {
      cluster_id: CLUSTER_UUID,
      identity_count: 2,
      representative_identity: {
        identity_id: 'identity-1',
        media_id: 101,
        media_url: 'https://example.com/instance-101.jpg',
        bbox: { x: 10, y: 20, width: 30, height: 40 },
        similarity: 0.95,
        similarity_threshold: 0.8,
      },
      instances: [
        {
          identity_id: 'identity-1',
          media_id: 101,
          media_url: 'https://example.com/instance-101.jpg',
          bbox: { x: 10, y: 20, width: 30, height: 40 },
          similarity: 0.95,
          similarity_threshold: 0.8,
        },
        {
          identity_id: 'identity-2',
          media_id: 102,
          media_url: 'https://example.com/instance-102.jpg',
          bbox: { x: 12, y: 22, width: 28, height: 36 },
          similarity: 0.62,
        },
      ],
    },
  ],
  queue_memberships: [],
  updated_at: '2026-05-07T12:00:00Z',
  source_version: 11,
  projection_status: 'current',
  projection_refreshed_at: '2026-05-07T12:00:00Z',
  ...overrides,
});

const RouteStateProbe = (): React.JSX.Element => {
  const [searchParams] = useSearchParams();
  return <output aria-label="route-state">{searchParams.toString()}</output>;
};

const renderWorkspace = (
  entry: RosterEntry = baseEntry(),
  route = '/?person=person-uuid-1',
): { user: ReturnType<typeof userEvent.setup>; queryClient: QueryClient } => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={queryClient}>
        <RouteStateProbe />
        <PersonWorkspacePanel entry={entry} onOpenQueue={vi.fn()} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { user, queryClient };
};

describe('PersonWorkspacePanel face scrubber', () => {
  beforeEach(() => {
    vi.mocked(pinRepresentative).mockReset();
    vi.mocked(pinRepresentative).mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
  });

  it('updates the preview and face route param when a filmstrip face is clicked', async () => {
    const { user } = renderWorkspace();

    const preview = screen.getByRole('img', { name: 'Selected face preview' });
    expect(preview).toHaveAttribute('src', 'https://example.com/instance-101.jpg');

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));

    expect(screen.getByRole('img', { name: 'Selected face preview' })).toHaveAttribute(
      'src',
      'https://example.com/instance-102.jpg',
    );
    expect(screen.getByLabelText('route-state')).toHaveTextContent('face=identity-2');
    expect(screen.getByLabelText('route-state')).toHaveTextContent('person=person-uuid-1');
  });

  it('moves the cursor with arrows and Home/End and announces the selected face', async () => {
    const { user } = renderWorkspace();

    const rail = screen.getByRole('listbox', { name: 'Face instances' });
    rail.focus();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent('face=identity-2');
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Selected face 2 of 2',
    );

    await user.keyboard('{Home}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent('face=identity-1');
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Selected face 1 of 2',
    );

    await user.keyboard('{End}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent('face=identity-2');
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Selected face 2 of 2',
    );
  });

  it('pins the selected face as representative with the cluster and identity ids', async () => {
    const { user } = renderWorkspace();

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
    await user.click(screen.getByRole('button', { name: 'Set as representative' }));

    expect(pinRepresentative).toHaveBeenCalledWith(CLUSTER_UUID, 'identity-2', true, expect.anything());
  });

  it('keeps the selected face and rail scroll across refetch and prunes a missing face', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const user = userEvent.setup();

    const Harness = ({ entry }: { entry: RosterEntry }): React.JSX.Element => (
      <MemoryRouter initialEntries={['/?person=person-uuid-1']}>
        <QueryClientProvider client={queryClient}>
          <RouteStateProbe />
          <PersonWorkspacePanel entry={entry} onOpenQueue={vi.fn()} />
        </QueryClientProvider>
      </MemoryRouter>
    );

    const { rerender } = render(<Harness entry={baseEntry()} />);

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
    const rail = screen.getByRole('listbox', { name: 'Face instances' });
    rail.scrollLeft = 48;

    rerender(<Harness entry={baseEntry({ source_version: 12 })} />);

    expect(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('listbox', { name: 'Face instances' }).scrollLeft).toBe(48);

    const pruned = baseEntry({
      clusters: [
        {
          cluster_id: CLUSTER_UUID,
          identity_count: 1,
          representative_identity: {
            identity_id: 'identity-1',
            media_id: 101,
            media_url: 'https://example.com/instance-101.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.95,
          },
          instances: [
            {
              identity_id: 'identity-1',
              media_id: 101,
              media_url: 'https://example.com/instance-101.jpg',
              bbox: { x: 10, y: 20, width: 30, height: 40 },
              similarity: 0.95,
            },
          ],
        },
      ],
    });

    rerender(<Harness entry={pruned} />);

    expect(screen.queryByRole('option', { name: 'Instance 102 for Cluster 1' })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Instance 101 for Cluster 1' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('gives rail cells explicit width and height before the image loads', () => {
    renderWorkspace();

    const option = screen.getByRole('option', { name: 'Instance 101 for Cluster 1' });
    const thumb = option.querySelector('.acx-face-thumbnail');
    expect(thumb).not.toBeNull();
    expect(thumb).toHaveStyle({ width: '64px', height: '64px' });
  });

  it('selects a face from the face= deep link and falls back without crashing when unmatched', () => {
    renderWorkspace(baseEntry(), '/?person=person-uuid-1&face=identity-2');

    expect(screen.getByRole('img', { name: 'Selected face preview' })).toHaveAttribute(
      'src',
      'https://example.com/instance-102.jpg',
    );
    expect(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' })).toHaveAttribute(
      'aria-selected',
      'true',
    );

    cleanup();
    renderWorkspace(baseEntry(), '/?person=person-uuid-1&face=missing-face');

    expect(screen.getByRole('region', { name: 'Person workspace: Alice' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Selected face preview' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Instance 101 for Cluster 1' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('still renders the workspace from an empty zero state', () => {
    renderWorkspace(
      baseEntry({
        cluster_count: 0,
        clusters: [],
      }),
    );

    expect(screen.getByRole('region', { name: 'Person workspace: Alice' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set as representative' })).toBeDisabled();
    expect(screen.queryByRole('img', { name: 'Selected face preview' })).not.toBeInTheDocument();
  });

  it('uses conservative similarity copy instead of bare percentages', async () => {
    const { user } = renderWorkspace();

    const metadata = screen.getByRole('region', { name: 'Selected face details' });
    expect(within(metadata).getByText('strong match')).toBeInTheDocument();
    expect(within(metadata).queryByText(/%/)).not.toBeInTheDocument();
    expect(within(metadata).getByText('Match evidence from current cluster response')).toBeInTheDocument();

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
    expect(within(screen.getByRole('region', { name: 'Selected face details' })).getByText('possible match')).toBeInTheDocument();
  });
});

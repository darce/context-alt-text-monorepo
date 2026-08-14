import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../api/queryKeys';
import type { RosterEntry } from '../../../api/rosterApi';
import { pinRepresentative } from '../../../api/recognition/clusterApiMutations';
import { PersonWorkspacePanel } from '../PersonWorkspacePanel';
import { toPersonFaceId } from '../personFaces';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%[sd]/g, () => String(args[index++]));
  },
}));

vi.mock('../../../api/recognition/clusterApiMutations', () => ({
  pinRepresentative: vi.fn(),
}));

const CLUSTER_UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const CLUSTER_B = 'bbbbbbbb-bbbb-cccc-dddd-ffffffffffff';
const encodedFace = (identityId: string, clusterId = CLUSTER_UUID): string =>
  `face=${encodeURIComponent(toPersonFaceId(clusterId, identityId))}`;

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

const twoClusterEntry = (): RosterEntry =>
  baseEntry({
    cluster_count: 2,
    clusters: [
      {
        cluster_id: CLUSTER_UUID,
        identity_count: 2,
        representative_identity: null,
        instances: [
          {
            identity_id: 'identity-a1',
            media_id: 101,
            media_url: 'https://example.com/instance-101.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.9,
          },
          {
            identity_id: 'identity-a2',
            media_id: 102,
            media_url: 'https://example.com/instance-102.jpg',
            bbox: { x: 12, y: 22, width: 28, height: 36 },
            similarity: 0.8,
          },
        ],
      },
      {
        cluster_id: CLUSTER_B,
        identity_count: 2,
        representative_identity: null,
        instances: [
          {
            identity_id: 'identity-b1',
            media_id: 201,
            media_url: 'https://example.com/instance-201.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.88,
          },
          {
            identity_id: 'identity-b2',
            media_id: 202,
            media_url: 'https://example.com/instance-202.jpg',
            bbox: { x: 12, y: 22, width: 28, height: 36 },
            similarity: 0.7,
          },
        ],
      },
    ],
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

const previewName = (instanceOrdinal: number, clusterOrdinal: number, mediaId: number): string =>
  `Selected face, instance ${instanceOrdinal} for Cluster ${clusterOrdinal}, media ${mediaId}`;

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

    const preview = screen.getByRole('img', { name: previewName(1, 1, 101) });
    expect(preview).toHaveAttribute('src', 'https://example.com/instance-101.jpg');

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));

    expect(screen.getByRole('img', { name: previewName(2, 1, 102) })).toHaveAttribute(
      'src',
      'https://example.com/instance-102.jpg',
    );
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-2'));
    expect(screen.getByLabelText('route-state')).toHaveTextContent('person=person-uuid-1');
  });

  it('moves the cursor with arrows and Home/End and announces the selected face', async () => {
    const { user } = renderWorkspace();

    const rail = screen.getByRole('listbox', { name: 'Face instances for Cluster 1' });
    expect(rail).toHaveAttribute('aria-orientation', 'horizontal');
    rail.focus();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-2'));
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Selected face 2 of 2',
    );

    await user.keyboard('{Home}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-1'));
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Selected face 1 of 2',
    );

    await user.keyboard('{End}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-2'));
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Selected face 2 of 2',
    );
  });

  it('maps ArrowUp/ArrowDown to the same horizontal cursor movement', async () => {
    const { user } = renderWorkspace();

    screen.getByRole('listbox', { name: 'Face instances for Cluster 1' }).focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-2'));

    await user.keyboard('{ArrowUp}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-1'));
  });

  it('keeps arrow keys inside the focused rail when multiple clusters exist', async () => {
    const { user } = renderWorkspace(twoClusterEntry());

    const cluster1Rail = screen.getByRole('listbox', { name: 'Face instances for Cluster 1' });
    const cluster2Rail = screen.getByRole('listbox', { name: 'Face instances for Cluster 2' });
    expect(cluster1Rail.getAttribute('aria-activedescendant')).toBeTruthy();
    expect(cluster2Rail.getAttribute('aria-activedescendant')).toBeNull();

    cluster1Rail.focus();
    await user.keyboard('{End}{ArrowRight}{ArrowDown}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-a2'));
    expect(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('option', { name: 'Instance 201 for Cluster 2' })).toHaveAttribute(
      'aria-selected',
      'false',
    );

    cluster2Rail.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-b1', CLUSTER_B));
    expect(screen.getByRole('option', { name: 'Instance 201 for Cluster 2' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Selected face 1 of 2',
    );
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).not.toHaveTextContent(
      'Selected face 3 of 4',
    );
    expect(cluster1Rail.getAttribute('aria-activedescendant')).toBeNull();
    expect(cluster2Rail.getAttribute('aria-activedescendant')).toBeTruthy();
  });

  it('re-announces an identical live-region string without remounting the status node', async () => {
    const { user } = renderWorkspace();

    const status = screen.getByRole('status', { name: 'Face selection announcements' });
    const statusNode = status;
    screen.getByRole('listbox', { name: 'Face instances for Cluster 1' }).focus();

    await user.keyboard('{End}');
    expect(status).toHaveTextContent('Selected face 2 of 2');
    const firstText = status.textContent;

    await user.keyboard('{End}');
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toBe(statusNode);
    expect(status.textContent).not.toBe(firstText);
    expect(status.textContent?.replace(/\u200b/g, '')).toBe('Selected face 2 of 2');
  });

  it('pins the selected face, invalidates caches, and disables the control while in flight', async () => {
    let resolvePin: (value: void | PromiseLike<void>) => void = () => undefined;
    vi.mocked(pinRepresentative).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePin = resolve;
        }),
    );

    const { user, queryClient } = renderWorkspace();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
    const pinButton = screen.getByRole('button', { name: 'Set as representative' });
    await user.click(pinButton);

    expect(pinRepresentative).toHaveBeenCalledWith(CLUSTER_UUID, 'identity-2', true, expect.any(AbortSignal));
    expect(pinButton).toBeDisabled();
    expect(invalidateSpy).not.toHaveBeenCalled();

    resolvePin();
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.roster.entries() });
    });
  });

  it('surfaces a pin failure through the announce channel and an inline notice', async () => {
    vi.mocked(pinRepresentative).mockRejectedValue(new Error('backend rejected pin'));
    const { user } = renderWorkspace();

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
    await user.click(screen.getByRole('button', { name: 'Set as representative' }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Could not set this face as representative.');
    });
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).toHaveTextContent(
      'Could not set this face as representative.',
    );
  });

  it('keeps AbortError pin failures silent', async () => {
    const abortError = Object.assign(new Error('Aborted'), { name: 'AbortError' });
    vi.mocked(pinRepresentative).mockRejectedValue(abortError);
    const { user } = renderWorkspace();

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
    await user.click(screen.getByRole('button', { name: 'Set as representative' }));

    await waitFor(() => {
      expect(pinRepresentative).toHaveBeenCalled();
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Face selection announcements' })).not.toHaveTextContent(
      'Could not set this face as representative.',
    );
  });

  it('keeps the selected face and rail scroll across refetch and prunes a missing face', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const user = userEvent.setup();
    const scrollAssignments: number[] = [];
    const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollLeft');

    Object.defineProperty(HTMLElement.prototype, 'scrollLeft', {
      configurable: true,
      get() {
        return (this as HTMLElement & { __acxScrollLeft?: number }).__acxScrollLeft ?? 0;
      },
      set(value: number) {
        const next = Number(value);
        (this as HTMLElement & { __acxScrollLeft?: number }).__acxScrollLeft = next;
        if ((this as HTMLElement).getAttribute?.('role') === 'listbox') {
          scrollAssignments.push(next);
        }
      },
    });

    const Harness = ({ entry }: { entry: RosterEntry }): React.JSX.Element => (
      <MemoryRouter initialEntries={['/?person=person-uuid-1']}>
        <QueryClientProvider client={queryClient}>
          <RouteStateProbe />
          <PersonWorkspacePanel entry={entry} onOpenQueue={vi.fn()} />
        </QueryClientProvider>
      </MemoryRouter>
    );

    try {
      const { rerender } = render(<Harness entry={baseEntry()} />);

      await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
      const rail = screen.getByRole('listbox', { name: 'Face instances for Cluster 1' });
      rail.scrollLeft = 48;
      scrollAssignments.length = 0;

      rerender(<Harness entry={baseEntry({ source_version: 12 })} />);

      expect(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' })).toHaveAttribute(
        'aria-selected',
        'true',
      );
      expect(scrollAssignments).toContain(48);
      expect(screen.getByRole('listbox', { name: 'Face instances for Cluster 1' }).scrollLeft).toBe(48);
      expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-2'));

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
      await waitFor(() => {
        expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-1'));
      });
      expect(screen.getByLabelText('route-state')).not.toHaveTextContent('identity-2');
    } finally {
      if (descriptor) {
        Object.defineProperty(HTMLElement.prototype, 'scrollLeft', descriptor);
      }
    }
  });

  it('moves focus to the surviving rail after the selected option is pruned', async () => {
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
    expect(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' })).toHaveFocus();

    rerender(
      <Harness
        entry={baseEntry({
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
        })}
      />,
    );

    expect(screen.getByRole('listbox', { name: 'Face instances for Cluster 1' })).toHaveFocus();
  });

  it('gives rail cells explicit width and height before the image loads', () => {
    const completeDescriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'complete');
    Object.defineProperty(HTMLImageElement.prototype, 'complete', {
      configurable: true,
      get: () => false,
    });

    try {
      renderWorkspace();

      const option = screen.getByRole('option', { name: 'Instance 101 for Cluster 1' });
      const thumb = option.querySelector('.acx-face-thumbnail');
      expect(thumb).not.toBeNull();
      expect(thumb).toHaveClass('acx-face-thumbnail--loading');
      expect(option.querySelector('.acx-face-thumbnail__placeholder')).not.toBeNull();
      expect(thumb).toHaveStyle({ width: '64px', height: '64px' });
    } finally {
      if (completeDescriptor) {
        Object.defineProperty(HTMLImageElement.prototype, 'complete', completeDescriptor);
      }
    }
  });

  it('reserves explicit width and height on the raw-image rail fallback', () => {
    renderWorkspace(
      baseEntry({
        clusters: [
          {
            cluster_id: CLUSTER_UUID,
            identity_count: 1,
            representative_identity: null,
            instances: [
              {
                identity_id: 'identity-raw',
                media_id: 303,
                media_url: 'https://example.com/zero-bbox.jpg',
                bbox: { x: 0, y: 0, width: 0, height: 0 },
                similarity: 0.5,
              },
            ],
          },
        ],
      }),
    );

    const image = screen.getByRole('img', { name: 'Instance 303 for Cluster 1' });
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('width', '64');
    expect(image).toHaveAttribute('height', '64');
  });

  it('selects a face from the face= deep link and falls back without crashing when unmatched', async () => {
    renderWorkspace(baseEntry(), '/?person=person-uuid-1&face=identity-2');

    expect(screen.getByRole('img', { name: previewName(2, 1, 102) })).toHaveAttribute(
      'src',
      'https://example.com/instance-102.jpg',
    );
    expect(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => {
      expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-2'));
    });

    cleanup();
    renderWorkspace(baseEntry(), '/?person=person-uuid-1&face=missing-face');

    expect(screen.getByRole('region', { name: 'Person workspace: Alice' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: previewName(1, 1, 101) })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Instance 101 for Cluster 1' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => {
      expect(screen.getByLabelText('route-state')).toHaveTextContent(encodedFace('identity-1'));
    });
    expect(screen.getByLabelText('route-state')).not.toHaveTextContent('missing-face');
  });

  it('still renders the workspace from an empty zero state', () => {
    renderWorkspace(
      baseEntry({
        cluster_count: 0,
        clusters: [],
      }),
    );

    const workspace = screen.getByRole('region', { name: 'Person workspace: Alice' });
    expect(workspace).toBeInTheDocument();
    expect(screen.getByText('Projection status: current')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Singleton proposals queue' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Hard examples queue' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Needs confirmation after merge queue' })).toBeInTheDocument();
    expect(
      screen.getByText('Assigned cluster evidence will appear after the next projection refresh.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Select a face to preview.')).toBeInTheDocument();
    expect(screen.getByText('No face selected.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set as representative' })).toBeDisabled();
    expect(screen.queryByRole('img', { name: /Selected face/ })).not.toBeInTheDocument();
  });

  it('uses conservative similarity copy instead of bare percentages', async () => {
    const { user } = renderWorkspace();

    const workspace = screen.getByRole('region', { name: 'Person workspace: Alice' });
    expect(workspace.textContent ?? '').not.toMatch(/%/);
    expect(within(workspace).getAllByText('strong match').length).toBeGreaterThan(0);

    const metadata = screen.getByRole('region', { name: 'Selected face details' });
    expect(within(metadata).getByText('strong match')).toBeInTheDocument();
    expect(within(metadata).getByText('Match evidence from current cluster response')).toBeInTheDocument();

    await user.click(screen.getByRole('option', { name: 'Instance 102 for Cluster 1' }));
    expect(
      within(screen.getByRole('region', { name: 'Selected face details' })).getByText('possible match'),
    ).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Person workspace: Alice' }).textContent ?? '').not.toMatch(/%/);
  });

  it('uses activedescendant listbox semantics with non-tabbable options', () => {
    renderWorkspace(twoClusterEntry());

    const rails = [
      screen.getByRole('listbox', { name: 'Face instances for Cluster 1' }),
      screen.getByRole('listbox', { name: 'Face instances for Cluster 2' }),
    ];
    expect(rails).toHaveLength(2);
    for (const rail of rails) {
      expect(rail).toHaveAttribute('tabIndex', '0');
      const options = within(rail).getAllByRole('option');
      expect(options.length).toBeGreaterThan(0);
      for (const option of options) {
        expect(option).toHaveAttribute('tabIndex', '-1');
      }
    }
    expect(screen.getByText('Selected')).toBeInTheDocument();
  });
});

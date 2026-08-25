import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { PersonWorkspacePanel } from '../PersonWorkspacePanel';

const Providers = ({ children }: { children: React.ReactNode }): React.JSX.Element => {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      }),
  );
  return (
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MemoryRouter>
  );
};

const renderPanel = (ui: React.ReactElement) => render(ui, { wrapper: Providers });

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
        identity_id: 'identity-rep',
        media_id: 100,
        media_url: 'https://example.com/rep.jpg',
        bbox: { x: 10, y: 20, width: 30, height: 40 },
        similarity: 0.95,
      },
      instances: [
        {
          identity_id: 'identity-1',
          media_id: 101,
          media_url: 'https://example.com/instance-101.jpg',
          bbox: { x: 10, y: 20, width: 30, height: 40 },
          similarity: 0.9,
        },
        {
          identity_id: 'identity-2',
          media_id: 102,
          media_url: null,
          bbox: null,
          similarity: null,
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

describe('PersonWorkspacePanel evidence images', () => {
  it('renders FaceThumbnail for croppable instances, not a raw 96px img', () => {
    renderPanel(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    const clusterRegion = screen.getByRole('region', { name: 'Face group 1' });
    const instanceImg = within(clusterRegion).getByRole('img', {
      name: 'Face from media 101 in face group 1',
    });
    expect(instanceImg.closest('.acx-face-thumbnail')).not.toBeNull();
    expect(instanceImg).not.toHaveAttribute('width', '96');
  });

  it('opens FaceLightbox when a croppable thumbnail button is clicked', async () => {
    const user = userEvent.setup();
    renderPanel(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Open original media' }));

    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();
  });

  it('resets lightbox when entry person identity changes', async () => {
    const user = userEvent.setup();
    const personA = baseEntry({ person_uuid: 'person-a', name: 'Alice' });
    const personB = baseEntry({
      id: 2,
      person_uuid: 'person-b',
      name: 'Bob',
      clusters: [
        {
          cluster_id: 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee',
          identity_count: 1,
          representative_identity: {
            identity_id: 'identity-rep-b',
            media_id: 200,
            media_url: 'https://example.com/rep-b.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.9,
          },
          instances: [
            {
              identity_id: 'identity-b1',
              media_id: 201,
              media_url: 'https://example.com/instance-201.jpg',
              bbox: { x: 10, y: 20, width: 30, height: 40 },
              similarity: 0.8,
            },
          ],
        },
      ],
    });

    const { rerender } = renderPanel(<PersonWorkspacePanel entry={personA} onOpenQueue={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Open original media' }));
    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();

    rerender(<PersonWorkspacePanel entry={personB} onOpenQueue={vi.fn()} />);

    expect(screen.queryByRole('dialog', { name: 'Original media with face highlight' })).not.toBeInTheDocument();
  });

  it('resets lightbox when entry id changes with empty person_uuid', async () => {
    const user = userEvent.setup();
    const entryId1 = baseEntry({ id: 1, person_uuid: '', name: 'Alice' });
    const entryId2 = baseEntry({
      id: 2,
      person_uuid: '',
      name: 'Bob',
      clusters: [
        {
          cluster_id: 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee',
          identity_count: 1,
          representative_identity: {
            identity_id: 'identity-rep-b',
            media_id: 200,
            media_url: 'https://example.com/rep-b.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.9,
          },
          instances: [
            {
              identity_id: 'identity-b1',
              media_id: 201,
              media_url: 'https://example.com/instance-201.jpg',
              bbox: { x: 10, y: 20, width: 30, height: 40 },
              similarity: 0.8,
            },
          ],
        },
      ],
    });

    const { rerender } = renderPanel(<PersonWorkspacePanel entry={entryId1} onOpenQueue={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Open original media' }));
    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();

    rerender(<PersonWorkspacePanel entry={entryId2} onOpenQueue={vi.fn()} />);

    expect(screen.queryByRole('dialog', { name: 'Original media with face highlight' })).not.toBeInTheDocument();
  });

  it('resets lightbox when person_uuid changes with the same entry id', async () => {
    const user = userEvent.setup();
    const personA = baseEntry({ id: 1, person_uuid: 'person-a', name: 'Alice' });
    const personB = baseEntry({
      id: 1,
      person_uuid: 'person-b',
      name: 'Bob',
      clusters: [
        {
          cluster_id: 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee',
          identity_count: 1,
          representative_identity: {
            identity_id: 'identity-rep-b',
            media_id: 200,
            media_url: 'https://example.com/rep-b.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.9,
          },
          instances: [
            {
              identity_id: 'identity-b1',
              media_id: 201,
              media_url: 'https://example.com/instance-201.jpg',
              bbox: { x: 10, y: 20, width: 30, height: 40 },
              similarity: 0.8,
            },
          ],
        },
      ],
    });

    const { rerender } = renderPanel(<PersonWorkspacePanel entry={personA} onOpenQueue={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Open original media' }));
    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();

    rerender(<PersonWorkspacePanel entry={personB} onOpenQueue={vi.fn()} />);

    expect(screen.queryByRole('dialog', { name: 'Original media with face highlight' })).not.toBeInTheDocument();
  });

  it('resets lightbox when person_uuid collides with prior entry id', async () => {
    const user = userEvent.setup();
    // Absent-uuid path uses String(id)="1"; next entry's person_uuid="1" collides without a composite key.
    const entryAbsentUuid = baseEntry({ id: 1, person_uuid: '', name: 'Alice' });
    const entryUuidEqualsPriorId = baseEntry({
      id: 2,
      person_uuid: '1',
      name: 'Bob',
      clusters: [
        {
          cluster_id: 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee',
          identity_count: 1,
          representative_identity: {
            identity_id: 'identity-rep-b',
            media_id: 200,
            media_url: 'https://example.com/rep-b.jpg',
            bbox: { x: 10, y: 20, width: 30, height: 40 },
            similarity: 0.9,
          },
          instances: [
            {
              identity_id: 'identity-b1',
              media_id: 201,
              media_url: 'https://example.com/instance-201.jpg',
              bbox: { x: 10, y: 20, width: 30, height: 40 },
              similarity: 0.8,
            },
          ],
        },
      ],
    });

    const { rerender } = renderPanel(<PersonWorkspacePanel entry={entryAbsentUuid} onOpenQueue={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Open original media' }));
    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();

    rerender(<PersonWorkspacePanel entry={entryUuidEqualsPriorId} onOpenQueue={vi.fn()} />);

    expect(screen.queryByRole('dialog', { name: 'Original media with face highlight' })).not.toBeInTheDocument();
  });

  it('closes lightbox via dialog close affordance and allows reopen', async () => {
    const user = userEvent.setup();
    renderPanel(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    const openButton = screen.getByRole('button', { name: 'Open original media' });
    await user.click(openButton);
    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog', { name: 'Original media with face highlight' })).not.toBeInTheDocument();

    await user.click(openButton);
    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();
  });

  it('shows visible No image fallback for missing media_url', () => {
    renderPanel(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Face from media 102 in face group 1' })).toHaveTextContent('No image');
  });

  it('falls back to raw lazy img for invalid-but-truthy bbox', () => {
    renderPanel(
      <PersonWorkspacePanel
        entry={baseEntry({
          clusters: [
            {
              cluster_id: CLUSTER_UUID,
              identity_count: 1,
              representative_identity: null,
              instances: [
                {
                  identity_id: 'identity-zero-bbox',
                  media_id: 303,
                  media_url: 'https://example.com/zero-bbox.jpg',
                  bbox: { x: 0, y: 0, width: 0, height: 0 },
                  similarity: 0.5,
                },
              ],
            },
          ],
        })}
        onOpenQueue={vi.fn()}
      />,
    );

    const image = screen.getByRole('img', { name: 'Face from media 303 in face group 1' });
    expect(image.tagName).toBe('IMG');
    expect(image).toHaveAttribute('loading', 'lazy');
    expect(image).toHaveAttribute('src', 'https://example.com/zero-bbox.jpg');
    expect(image.closest('.acx-face-thumbnail')).toBeNull();
    expect(image.closest('[role="option"]')).not.toBeNull();
  });

  it('passes loading=lazy on FaceThumbnail croppable branch and raw-img fallback', () => {
    renderPanel(
      <PersonWorkspacePanel
        entry={baseEntry({
          clusters: [
            {
              cluster_id: CLUSTER_UUID,
              identity_count: 2,
              representative_identity: {
                identity_id: 'identity-rep',
                media_id: 100,
                media_url: 'https://example.com/rep.jpg',
                bbox: { x: 10, y: 20, width: 30, height: 40 },
                similarity: 0.95,
              },
              instances: [
                {
                  identity_id: 'identity-1',
                  media_id: 101,
                  media_url: 'https://example.com/instance-101.jpg',
                  bbox: { x: 10, y: 20, width: 30, height: 40 },
                  similarity: 0.9,
                },
                {
                  identity_id: 'identity-raw',
                  media_id: 104,
                  media_url: 'https://example.com/raw.jpg',
                  bbox: { x: 0, y: 0, width: 0, height: 0 },
                  similarity: 0.4,
                },
              ],
            },
          ],
        })}
        onOpenQueue={vi.fn()}
      />,
    );

    const croppable = screen.getByRole('img', { name: 'Face from media 101 in face group 1' });
    expect(croppable).toHaveAttribute('loading', 'lazy');

    const rawFallback = screen.getByRole('img', { name: 'Face from media 104 in face group 1' });
    expect(rawFallback.tagName).toBe('IMG');
    expect(rawFallback).toHaveAttribute('loading', 'lazy');
  });

  it('keeps thumbnail button accessible name when FaceThumbnail errors', async () => {
    renderPanel(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    const openButton = screen.getByRole('option', { name: 'Face from media 101 in face group 1' });
    const img = within(openButton).getByRole('img');
    fireEvent.error(img);

    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Face from media 101 in face group 1' })).toBeInTheDocument();
      expect(within(openButton).getByRole('img', { name: 'Face image unavailable' })).toBeInTheDocument();
    });
    expect(screen.queryByRole('option', { name: 'Face image unavailable' })).not.toBeInTheDocument();
  });

  it('shows Face group 1 and Media captions without visible uuids', () => {
    renderPanel(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    expect(screen.getByRole('heading', { level: 5, name: 'Face group 1' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Face group 1' })).toBeInTheDocument();
    expect(screen.getByText('Media 101')).toBeInTheDocument();
    expect(screen.queryByText(CLUSTER_UUID)).not.toBeInTheDocument();
    expect(screen.queryByText(/Identity /)).not.toBeInTheDocument();
  });

  it('uses ordinal face group alts and never exposes fixture uuid in accessible names', () => {
    renderPanel(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    expect(screen.getByRole('img', { name: 'Representative face for face group 1' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Face from media 101 in face group 1' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Face from media 102 in face group 1' })).toBeInTheDocument();

    for (const role of ['img', 'button', 'region'] as const) {
      expect(screen.queryByRole(role, { name: new RegExp(CLUSTER_UUID, 'i') })).toBeNull();
    }
  });

  it('renders distinct ordinal accessible names for multi-group evidence', () => {
    const clusterA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
    const clusterB = 'bbbbbbbb-bbbb-cccc-dddd-ffffffffffff';
    renderPanel(
      <PersonWorkspacePanel
        entry={baseEntry({
          cluster_count: 2,
          clusters: [
            {
              cluster_id: clusterA,
              identity_count: 2,
              representative_identity: {
                identity_id: 'identity-rep-a',
                media_id: 100,
                media_url: 'https://example.com/rep-a.jpg',
                bbox: { x: 10, y: 20, width: 30, height: 40 },
                similarity: 0.95,
              },
              instances: [
                {
                  identity_id: 'identity-a1',
                  media_id: 101,
                  media_url: 'https://example.com/instance-101.jpg',
                  bbox: { x: 10, y: 20, width: 30, height: 40 },
                  similarity: 0.9,
                },
              ],
            },
            {
              cluster_id: clusterB,
              identity_count: 2,
              representative_identity: {
                identity_id: 'identity-rep-b',
                media_id: 200,
                media_url: 'https://example.com/rep-b.jpg',
                bbox: { x: 10, y: 20, width: 30, height: 40 },
                similarity: 0.91,
              },
              instances: [
                {
                  identity_id: 'identity-b1',
                  media_id: 201,
                  media_url: 'https://example.com/instance-201.jpg',
                  bbox: { x: 10, y: 20, width: 30, height: 40 },
                  similarity: 0.88,
                },
              ],
            },
          ],
        })}
        onOpenQueue={vi.fn()}
      />,
    );

    const repCluster1 = screen.getByRole('img', { name: 'Representative face for face group 1' });
    const repCluster2 = screen.getByRole('img', { name: 'Representative face for face group 2' });
    expect(repCluster1).toBeInTheDocument();
    expect(repCluster2).toBeInTheDocument();
    expect(repCluster1).not.toBe(repCluster2);

    expect(screen.getByRole('img', { name: 'Face from media 201 in face group 2' })).toBeInTheDocument();

    for (const role of ['img', 'button', 'region'] as const) {
      expect(screen.queryByRole(role, { name: new RegExp(clusterA, 'i') })).toBeNull();
      expect(screen.queryByRole(role, { name: new RegExp(clusterB, 'i') })).toBeNull();
    }

    const cluster2Region = screen.getByRole('region', { name: 'Face group 2' });
    expect(within(cluster2Region).getByText('Media 201')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Face group 1' })).getByText('Media 101')).toBeInTheDocument();
  });
});

describe('D-23 PersonWorkspacePanel failure states', () => {
  it('renders linked-faces error when projection failed', () => {
    renderPanel(
      <PersonWorkspacePanel
        entry={baseEntry({ projection_status: 'failed', cluster_count: 4 })}
        onOpenQueue={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load linked faces.');
    expect(screen.queryByText('4 face groups assigned')).not.toBeInTheDocument();
  });

  it('renders linked-faces degraded when projection is stale', () => {
    renderPanel(
      <PersonWorkspacePanel entry={baseEntry({ projection_status: 'stale' })} onOpenQueue={vi.fn()} />,
    );
    expect(screen.getByText('Linked faces may be out of date.')).toBeInTheDocument();
  });

  it('labels refreshing distinctly from stale', () => {
    renderPanel(
      <PersonWorkspacePanel entry={baseEntry({ projection_status: 'refreshing' })} onOpenQueue={vi.fn()} />,
    );
    expect(screen.getByText('Refreshing linked faces…')).toBeInTheDocument();
    expect(screen.queryByText('Linked faces may be out of date.')).not.toBeInTheDocument();
  });
});

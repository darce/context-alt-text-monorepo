import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { PersonWorkspacePanel } from '../PersonWorkspacePanel';

const baseEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: 'person-uuid-1',
  name: 'Alice',
  tags: [],
  cluster_count: 1,
  clusters: [
    {
      cluster_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
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
    render(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    const clusterRegion = screen.getByRole('region', { name: 'Cluster 1' });
    const instanceImg = within(clusterRegion).getByRole('img', {
      name: 'Instance 101 for cluster aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    });
    expect(instanceImg.closest('.acx-face-thumbnail')).not.toBeNull();
    expect(instanceImg).not.toHaveAttribute('width', '96');
  });

  it('opens FaceLightbox when a croppable thumbnail button is clicked', async () => {
    const user = userEvent.setup();
    render(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    const openButton = screen.getByRole('button', {
      name: 'Instance 101 for cluster aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    });
    await user.click(openButton);

    expect(screen.getByRole('dialog', { name: 'Original media with face highlight' })).toBeInTheDocument();
  });

  it('shows visible No image fallback for missing media_url', () => {
    render(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    expect(screen.getByText('No image')).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: 'Instance 102 for cluster aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' }),
    ).toHaveTextContent('No image');
  });

  it('shows Cluster 1 and Media captions without visible uuids', () => {
    const uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
    render(<PersonWorkspacePanel entry={baseEntry()} onOpenQueue={vi.fn()} />);

    expect(screen.getByRole('heading', { level: 5, name: 'Cluster 1' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Cluster 1' })).toBeInTheDocument();
    expect(screen.getByText('Media 101')).toBeInTheDocument();
    expect(screen.queryByText(uuid)).not.toBeInTheDocument();
    expect(screen.queryByText(/Identity /)).not.toBeInTheDocument();
  });
});

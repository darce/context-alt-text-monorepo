import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterIdentity, ClusterSummary } from '../../../api/recognition';
import type { RosterEntry } from '../../../api/rosterApi';
import { ClusterDrawerPanel, ROSTER_ASSIGN_STATUS } from '../ClusterDrawerPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[ds]|%\d+\$[ds]/g, () => String(args[i++]));
  },
}));

const UUID_A = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
const UUID_B = 'b2c3d4e5-f6a7-8901-bcde-f12345678901';
const UUID_C = 'c3d4e5f6-a7b8-9012-cdef-123456789012';
const HEX_FRAG_A = UUID_A.slice(0, 8);
const HEX_FRAG_B = UUID_B.slice(0, 8);
const HEX_FRAG_C = UUID_C.slice(0, 8);

const unlabeledCluster: ClusterSummary = {
  id: UUID_A,
  label: null,
  identity_count: 1,
  member_ids: ['identity-1'],
  representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 100, height: 100 } },
  sample_identities: [],
};

const labeledCluster: ClusterSummary = {
  ...unlabeledCluster,
  id: 'cluster-labeled',
  label: 'Alex Rivera',
};

const identities: ClusterIdentity[] = [
  {
    identity_id: 'identity-1',
    media_id: 1,
    similarity: 0.9,
    confidence: 0.9,
    bbox: null,
  },
];

const baseProps = {
  identities,
  mediaMap: {},
  onClose: () => undefined,
  onRescanCluster: vi.fn(),
  isRescanning: false,
  onCommitCluster: () => undefined,
  onOpenPersonWorkspace: () => undefined,
  isCommitting: false,
  rosterEntries: [],
  isDetailLoading: false,
  onFaceDragStart: () => undefined,
  onFaceDragEnd: () => undefined,
  onDropTargetChange: () => undefined,
  dropTarget: null,
  isDragging: false,
  onDiscardDrop: () => undefined,
};

/** Collect visible text + accessible names from the drawer tree. */
const collectVisibleAndAccessibleText = (root: HTMLElement): string => {
  const chunks: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  let node: Node | null = walker.currentNode;
  while (node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent?.trim();
      if (text) {
        chunks.push(text);
      }
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as HTMLElement;
      for (const attr of ['aria-label', 'aria-describedby', 'title', 'alt'] as const) {
        const value = el.getAttribute(attr);
        if (value) {
          if (attr === 'aria-describedby') {
            for (const id of value.split(/\s+/)) {
              const ref = document.getElementById(id);
              if (ref?.textContent) {
                chunks.push(ref.textContent);
              }
            }
          } else {
            chunks.push(value);
          }
        }
      }
    }
    node = walker.nextNode();
  }
  return chunks.join('\n');
};

const rosterEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: UUID_B,
  name: 'Pat',
  tags: [],
  cluster_count: 1,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-05-07T12:00:00Z',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: '2026-05-07T12:00:00Z',
  ...overrides,
});

describe('D-23 ClusterDrawerPanel assignment failure states', () => {
  it('renders empty assign actions when there are no named people', () => {
    render(<ClusterDrawerPanel {...baseProps} cluster={unlabeledCluster} rosterEntries={[]} />);
    expect(screen.getByText('No named people to assign yet.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Review Queue' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('renders assign loading from roster query status', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={unlabeledCluster}
        rosterEntries={[]}
        rosterStatus={ROSTER_ASSIGN_STATUS.loading}
      />,
    );
    expect(screen.getByText('Loading people to assign…')).toBeInTheDocument();
    expect(screen.queryByText('No named people to assign yet.')).not.toBeInTheDocument();
  });

  it('renders assign error from roster query status', () => {
    const onRetryRoster = vi.fn();
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={unlabeledCluster}
        rosterEntries={[]}
        rosterStatus={ROSTER_ASSIGN_STATUS.error}
        onRetryRoster={onRetryRoster}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load people to assign.');
    expect(screen.queryByText('No named people to assign yet.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetryRoster).toHaveBeenCalledTimes(1);
  });

  it('renders assign error', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={unlabeledCluster}
        rosterEntries={[rosterEntry()]}
        reassignErrorMessage="Could not assign this face group."
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Could not assign this face group.');
  });
});

describe('ClusterDrawerPanel humane cluster labels (E21-16)', () => {
  it('shows Unnamed face group for unlabeled drawer title with no uuid hex fragment', () => {
    const { container } = render(
      <ClusterDrawerPanel {...baseProps} cluster={unlabeledCluster} />,
    );

    const title = container.querySelector('.acx-cluster-drawer__title');
    expect(title).toHaveTextContent('Unnamed face group');
    expect(title).not.toHaveTextContent(HEX_FRAG_A);
    expect(title).not.toHaveTextContent(/^Cluster /);

    const surface = collectVisibleAndAccessibleText(container);
    expect(surface).not.toMatch(new RegExp(HEX_FRAG_A, 'i'));
    expect(surface).not.toMatch(/Cluster [0-9a-f]{8}/i);
  });

  it('keeps a human label when the cluster is labeled (control)', () => {
    const { container } = render(
      <ClusterDrawerPanel {...baseProps} cluster={labeledCluster} />,
    );

    const title = container.querySelector('.acx-cluster-drawer__title');
    expect(title).toHaveTextContent('Alex Rivera');
    expect(screen.queryByText('Unnamed face group')).not.toBeInTheDocument();
  });

  it('shows distinct humane labels for unlabeled reassign targets (no uuid fragments)', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={unlabeledCluster}
        onReassignFace={vi.fn()}
        reassignTargets={[
          { id: UUID_B, label: '' },
          { id: UUID_C, label: '   ' },
          { id: 'cluster-named', label: 'Jordan Lee' },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Move to… face from media/ }));

    const menu = screen.getByRole('menu', { name: 'Choose a target face group' });
    const options = within(menu).getAllByRole('menuitem');
    const optionLabels = options
      .filter((btn) => btn.textContent !== 'Cancel')
      .map((btn) => btn.textContent ?? '');

    expect(optionLabels).toEqual(['Unnamed face group 1', 'Unnamed face group 2', 'Jordan Lee']);
    expect(new Set(optionLabels).size).toBe(optionLabels.length);

    const menuText = collectVisibleAndAccessibleText(menu);
    expect(menuText).not.toMatch(new RegExp(HEX_FRAG_B, 'i'));
    expect(menuText).not.toMatch(new RegExp(HEX_FRAG_C, 'i'));
    expect(menuText).not.toMatch(/Cluster [0-9a-f]{8}/i);
  });
});

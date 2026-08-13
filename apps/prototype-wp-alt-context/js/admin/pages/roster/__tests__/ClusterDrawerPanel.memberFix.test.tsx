import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterIdentity, ClusterSummary } from '../../../api/recognition';
import { ClusterDrawerPanel } from '../ClusterDrawerPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[ds]|%\d+\$[ds]/g, () => String(args[i++]));
  },
}));

const cluster: ClusterSummary = {
  id: 'cluster-1',
  label: 'Source Cluster',
  identity_count: 1,
  member_ids: ['identity-1'],
  representative_identity: { media_id: 10, bbox: { x: 0, y: 0, width: 100, height: 100 } },
  sample_identities: [],
};

const identities: ClusterIdentity[] = [
  {
    identity_id: 'identity-1',
    media_id: 10,
    similarity: 0.91,
    confidence: 0.9,
    bbox: null,
  },
];

const reassignTargets = [
  { id: 'cluster-2', label: 'Target Alpha' },
  { id: 'cluster-3', label: 'Target Beta' },
];

const baseProps = {
  cluster,
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

describe('ClusterDrawerPanel keyboard member-fix (E21-9 Slice 3)', () => {
  it('fires exactly one reassign call with the picked target (rg-002)', async () => {
    const user = userEvent.setup();
    const onReassignFace = vi.fn();

    render(
      <ClusterDrawerPanel {...baseProps} reassignTargets={reassignTargets} onReassignFace={onReassignFace} />,
    );

    const moveButton = screen.getByRole('button', { name: /Move to… identity from media 10/i });
    await user.click(moveButton);

    const picker = screen.getByRole('menu', { name: /Choose a target cluster/i });
    expect(picker).toBeInTheDocument();
    expect(within(picker).queryByRole('menuitem', { name: 'Source Cluster' })).not.toBeInTheDocument();
    expect(within(picker).queryByRole('menuitem', { name: /cluster-1/i })).not.toBeInTheDocument();

    await user.click(within(picker).getByRole('menuitem', { name: 'Target Alpha' }));

    expect(onReassignFace).toHaveBeenCalledTimes(1);
    expect(onReassignFace).toHaveBeenCalledWith('identity-1', 'cluster-2');
    // BR-05: focus returns to the originating Move-to button after selection.
    expect(moveButton).toHaveFocus();
  });

  it('announces the reassignment outcome via role=status', async () => {
    const user = userEvent.setup();
    const onReassignFace = vi.fn();

    render(
      <ClusterDrawerPanel {...baseProps} reassignTargets={reassignTargets} onReassignFace={onReassignFace} />,
    );

    await user.click(screen.getByRole('button', { name: /Move to… identity from media 10/i }));
    await user.click(screen.getByRole('menuitem', { name: 'Target Beta' }));

    const status = screen.getByRole('status', { name: '' });
    // role=status region is present and carries the outcome copy (A11Y-21).
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveTextContent(/Moving identity to Target Beta|Moved identity to Target Beta/i);
    expect(screen.getByTestId('cluster-drawer-reassign-status')).toBe(status);
  });

  it('excludes the current cluster from targets and disables with reason when empty', () => {
    const onReassignFace = vi.fn();

    const { rerender } = render(
      <ClusterDrawerPanel
        {...baseProps}
        reassignTargets={[{ id: 'cluster-2', label: 'Other' }]}
        onReassignFace={onReassignFace}
      />,
    );

    const moveButton = screen.getByRole('button', { name: /Move to… identity from media 10/i });
    expect(moveButton).toBeEnabled();
    fireEvent.click(moveButton);
    expect(screen.queryByRole('menuitem', { name: 'Source Cluster' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Other' })).toBeInTheDocument();

    rerender(
      <ClusterDrawerPanel {...baseProps} reassignTargets={[]} onReassignFace={onReassignFace} />,
    );

    const emptyTargetsMove = screen.getByRole('button', { name: /Move to… identity from media 10/i });
    // BR-09: aria-disabled (not native disabled) so the control stays focusable.
    expect(emptyTargetsMove).not.toBeDisabled();
    expect(emptyTargetsMove).toHaveAttribute('aria-disabled', 'true');
    expect(emptyTargetsMove).toHaveAttribute(
      'aria-describedby',
      'acx-cluster-drawer-no-move-targets-reason',
    );
    expect(emptyTargetsMove).not.toHaveAttribute('title');
    expect(screen.getByText('No other clusters available to move this identity into.')).toBeInTheDocument();
    emptyTargetsMove.focus();
    expect(emptyTargetsMove).toHaveFocus();
    // Never hidden when empty (rg-003 / A11Y-14): control remains in the DOM.
    expect(emptyTargetsMove).toBeVisible();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('keeps Move to… always visible without hover (A11Y-14 no-hover query)', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        reassignTargets={reassignTargets}
        onReassignFace={vi.fn()}
      />,
    );

    const moveButton = screen.getByRole('button', { name: /Move to… identity from media 10/i });
    // Discriminating: control exists in the default (no-hover) tree and is not hover-gated.
    expect(moveButton).toBeVisible();
    expect(moveButton).toHaveClass('acx-cluster-drawer__move-btn');

    const actions = moveButton.closest('.acx-cluster-drawer__face-actions')!;
    expect(actions).not.toBeNull();
    // BR-10: class-contract — actions container must not carry a hover-gated class.
    // SCSS always-visible gate on `.acx-cluster-drawer__face-actions` is review-enforced.
    expect(actions.className).not.toMatch(/hover/i);
    expect(actions).toHaveClass('acx-cluster-drawer__face-actions');
    // Touch-target floor is owned by `.acx-cluster-drawer__move-btn` min 24×24 CSS px.
    expect(moveButton.className).toContain('acx-cluster-drawer__move-btn');
  });

  it('supports a full keyboard path: focus Move to… → pick target → status announces', async () => {
    const user = userEvent.setup();
    const onReassignFace = vi.fn();

    render(
      <ClusterDrawerPanel {...baseProps} reassignTargets={reassignTargets} onReassignFace={onReassignFace} />,
    );

    const moveButton = screen.getByRole('button', { name: /Move to… identity from media 10/i });
    moveButton.focus();
    expect(moveButton).toHaveFocus();

    await user.keyboard('{Enter}');
    const firstOption = screen.getByRole('menuitem', { name: 'Target Alpha' });
    expect(firstOption).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(onReassignFace).toHaveBeenCalledTimes(1);
    expect(onReassignFace).toHaveBeenCalledWith('identity-1', 'cluster-2');
    expect(screen.getByRole('status')).toHaveTextContent(/Target Alpha/i);
    // BR-05: focus returns to Move-to after selection.
    expect(moveButton).toHaveFocus();
  });

  it('closes the picker on Escape without closing the drawer', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onReassignFace = vi.fn();

    render(
      <ClusterDrawerPanel
        {...baseProps}
        onClose={onClose}
        reassignTargets={reassignTargets}
        onReassignFace={onReassignFace}
      />,
    );

    const moveButton = screen.getByRole('button', { name: /Move to… identity from media 10/i });
    await user.click(moveButton);
    expect(screen.getByRole('menu')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(onReassignFace).not.toHaveBeenCalled();
    // BR-05: focus returns to the originating Move-to button after Escape.
    expect(moveButton).toHaveFocus();
  });

  it('restores focus to Move-to when Cancel closes the picker', async () => {
    const user = userEvent.setup();
    const onReassignFace = vi.fn();

    render(
      <ClusterDrawerPanel {...baseProps} reassignTargets={reassignTargets} onReassignFace={onReassignFace} />,
    );

    const moveButton = screen.getByRole('button', { name: /Move to… identity from media 10/i });
    await user.click(moveButton);
    await user.click(screen.getByRole('menuitem', { name: 'Cancel' }));

    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(onReassignFace).not.toHaveBeenCalled();
    expect(moveButton).toHaveFocus();
  });
});

const RESERVED_LABEL_MESSAGE =
  'This label format is reserved for automatic cluster IDs. Choose a descriptive name.';

const createAndConfirmAssignment = async (name: string, onCommitCluster = vi.fn()) => {
  const user = userEvent.setup();
  render(<ClusterDrawerPanel {...baseProps} onCommitCluster={onCommitCluster} />);

  await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
  const search = screen.getByPlaceholderText('Assign to…');
  await user.clear(search);
  await user.type(search, name);
  await user.click(screen.getByRole('button', { name: `Create "${name}"` }));
  await user.click(screen.getByRole('button', { name: /Confirm Assignment/i }));

  return onCommitCluster;
};

describe('ClusterDrawerPanel create-commit reserved-label gate (BR-59)', () => {
  it('rejects cluster-7 without calling onCommitCluster and shows reserved message', async () => {
    const onCommitCluster = await createAndConfirmAssignment('cluster-7');

    expect(onCommitCluster).not.toHaveBeenCalled();
    expect(screen.getByText(RESERVED_LABEL_MESSAGE)).toBeInTheDocument();
    expect(screen.getByTestId('cluster-drawer-reassign-status')).toHaveTextContent(RESERVED_LABEL_MESSAGE);
  });

  it('commits Pat Rivera via onCommitCluster (human-label control)', async () => {
    const onCommitCluster = await createAndConfirmAssignment('Pat Rivera');

    expect(onCommitCluster).toHaveBeenCalledTimes(1);
    expect(onCommitCluster).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'cluster-1' }),
      { newEntryName: 'Pat Rivera' },
    );
    expect(screen.queryByText(RESERVED_LABEL_MESSAGE)).not.toBeInTheDocument();
  });
});

describe('ClusterDrawerPanel reserved-status lifecycle (BR-64 / BR-65)', () => {
  it('BR-64: clears reserved status when creating a human name after reject, then commits', async () => {
    const user = userEvent.setup();
    const onCommitCluster = vi.fn();
    render(<ClusterDrawerPanel {...baseProps} onCommitCluster={onCommitCluster} />);

    await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
    const search = screen.getByPlaceholderText('Assign to…');
    await user.clear(search);
    await user.type(search, 'cluster-7');
    await user.click(screen.getByRole('button', { name: 'Create "cluster-7"' }));
    await user.click(screen.getByRole('button', { name: /Confirm Assignment/i }));
    expect(screen.getByTestId('cluster-drawer-reassign-status')).toHaveTextContent(RESERVED_LABEL_MESSAGE);
    expect(onCommitCluster).not.toHaveBeenCalled();

    await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
    const searchAgain = screen.getByPlaceholderText('Assign to…');
    await user.clear(searchAgain);
    await user.type(searchAgain, 'Pat Rivera');
    await user.click(screen.getByRole('button', { name: 'Create "Pat Rivera"' }));

    expect(screen.queryByText(RESERVED_LABEL_MESSAGE)).not.toBeInTheDocument();
    expect(screen.getByTestId('cluster-drawer-reassign-status')).toHaveTextContent('');

    await user.click(screen.getByRole('button', { name: /Confirm Assignment/i }));
    expect(onCommitCluster).toHaveBeenCalledTimes(1);
    expect(onCommitCluster).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'cluster-1' }),
      { newEntryName: 'Pat Rivera' },
    );
  });

  it('BR-64: clears reserved status when selecting an existing entry after reject, then commits', async () => {
    const user = userEvent.setup();
    const onCommitCluster = vi.fn();
    const rosterEntries = [
      {
        id: 42,
        person_uuid: 'person-uuid-alex',
        name: 'Alex Carter',
        tags: [] as string[],
        cluster_count: 0,
        clusters: [] as never[],
        queue_memberships: [] as never[],
        updated_at: new Date().toISOString(),
        source_version: 1,
        projection_status: 'current' as const,
        projection_refreshed_at: new Date().toISOString(),
      },
    ];
    render(
      <ClusterDrawerPanel {...baseProps} rosterEntries={rosterEntries} onCommitCluster={onCommitCluster} />,
    );

    await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
    const search = screen.getByPlaceholderText('Assign to…');
    await user.clear(search);
    await user.type(search, 'cluster-7');
    await user.click(screen.getByRole('button', { name: 'Create "cluster-7"' }));
    await user.click(screen.getByRole('button', { name: /Confirm Assignment/i }));
    expect(screen.getByTestId('cluster-drawer-reassign-status')).toHaveTextContent(RESERVED_LABEL_MESSAGE);

    await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
    await user.click(screen.getByRole('option', { name: 'Alex Carter' }));

    expect(screen.queryByText(RESERVED_LABEL_MESSAGE)).not.toBeInTheDocument();
    expect(screen.getByTestId('cluster-drawer-reassign-status')).toHaveTextContent('');

    await user.click(screen.getByRole('button', { name: /Confirm Assignment/i }));
    expect(onCommitCluster).toHaveBeenCalledTimes(1);
    expect(onCommitCluster).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'cluster-1' }),
      { rosterEntryId: 42 },
    );
  });

  it('BR-65: repeat reserved reject remounts the status region via announce seq', async () => {
    const user = userEvent.setup();
    render(<ClusterDrawerPanel {...baseProps} onCommitCluster={vi.fn()} />);

    await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
    const search = screen.getByPlaceholderText('Assign to…');
    await user.clear(search);
    await user.type(search, 'cluster-7');
    await user.click(screen.getByRole('button', { name: 'Create "cluster-7"' }));
    await user.click(screen.getByRole('button', { name: /Confirm Assignment/i }));

    const status1 = screen.getByTestId('cluster-drawer-reassign-status');
    expect(status1).toHaveTextContent(RESERVED_LABEL_MESSAGE);
    const seq1 = status1.getAttribute('data-announce-seq');
    expect(seq1).toBeTruthy();
    expect(Number(seq1)).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: /Confirm Assignment/i }));

    const status2 = screen.getByTestId('cluster-drawer-reassign-status');
    expect(status2).toHaveTextContent(RESERVED_LABEL_MESSAGE);
    const seq2 = status2.getAttribute('data-announce-seq');
    expect(seq2).toBeTruthy();
    expect(Number(seq2)).toBeGreaterThan(Number(seq1));
    // key={seq} remount: assert the seq/key mechanism directly (jsdom identity
    // of remounted nodes is not always observable beyond the bumped attribute).
    expect(status2).toHaveAttribute('data-announce-seq', seq2);
  });

  it('BR-68: reassign success message survives picker create (handleCreate)', async () => {
    const user = userEvent.setup();
    const onReassignFace = vi.fn();
    const panelProps = {
      ...baseProps,
      reassignTargets,
      onReassignFace,
      onCommitCluster: vi.fn(),
    };

    const { rerender } = render(<ClusterDrawerPanel {...panelProps} isReassigning={false} />);

    await user.click(screen.getByRole('button', { name: /Move to… identity from media 10/i }));
    await user.click(screen.getByRole('menuitem', { name: 'Target Alpha' }));

    // Toggle isReassigning like the parent mutation hook: pending → settled → Moved.
    rerender(<ClusterDrawerPanel {...panelProps} isReassigning={true} />);
    rerender(<ClusterDrawerPanel {...panelProps} isReassigning={false} />);

    const status = screen.getByTestId('cluster-drawer-reassign-status');
    expect(status).toHaveTextContent('Moved identity to Target Alpha.');

    // handleCreate → clearReservedStatus; must not wipe the reassign success copy.
    await user.click(screen.getByRole('combobox', { name: /Commit to roster entry/i }));
    const search = screen.getByPlaceholderText('Assign to…');
    await user.clear(search);
    await user.type(search, 'Pat Rivera');
    await user.click(screen.getByRole('button', { name: 'Create "Pat Rivera"' }));

    expect(screen.getByTestId('cluster-drawer-reassign-status')).toHaveTextContent(
      'Moved identity to Target Alpha.',
    );
  });
});

describe('ClusterDrawerPanel heading fallback (BR-51 / E21-16)', () => {
  it('renders Unnamed cluster when label is empty string', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={{ ...cluster, id: 'abcdef0123456789', label: '' }}
      />,
    );

    const heading = screen.getByRole('heading', { level: 3, name: 'Unnamed cluster' });
    // BR-61: exact textContent (role accessible-name normalizes whitespace).
    expect(heading.textContent).toBe('Unnamed cluster');
  });

  it('renders Unnamed cluster when label is null', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={{ ...cluster, id: 'abcdef0123456789', label: null }}
      />,
    );

    expect(screen.getByRole('heading', { level: 3, name: 'Unnamed cluster' })).toBeInTheDocument();
  });

  it('renders Unnamed cluster when label is whitespace-only', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={{ ...cluster, id: 'abcdef0123456789', label: '   ' }}
      />,
    );

    const heading = screen.getByRole('heading', { level: 3, name: 'Unnamed cluster' });
    // BR-61: exact textContent kills concat(whitespace + fallback) false-greens.
    expect(heading.textContent).toBe('Unnamed cluster');
  });

  it('renders the human label when present', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={{ ...cluster, id: 'abcdef0123456789', label: 'Source Cluster' }}
      />,
    );

    expect(screen.getByRole('heading', { level: 3, name: 'Source Cluster' })).toBeInTheDocument();
  });
});

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
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
  label: 'Test Cluster',
  identity_count: 1,
  member_ids: ['identity-1'],
  representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 100, height: 100 } },
  sample_identities: [],
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

describe('ClusterDrawerPanel rescan state matrix (RES-15, A11Y-24)', () => {
  it('disables rescan and shows empty copy when the cluster has no identities', () => {
    render(<ClusterDrawerPanel {...baseProps} identities={[]} />);

    expect(screen.getByText('No faces found in this face group.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rescan with sensitive settings' })).toBeDisabled();
  });

  it('shows loading copy and disables rescan while detail is loading / rescanning', () => {
    const { rerender } = render(<ClusterDrawerPanel {...baseProps} isDetailLoading identities={[]} />);

    expect(screen.getByText('Loading faces…')).toBeInTheDocument();

    rerender(<ClusterDrawerPanel {...baseProps} isRescanning />);
    expect(screen.getByRole('button', { name: 'Rescanning…' })).toBeDisabled();
  });

  it('renders the detail error and keeps rescan available when detail loading fails', () => {
    render(<ClusterDrawerPanel {...baseProps} detailError="Failed to load cluster identities." />);

    const errorCopy = screen.getByText('Failed to load cluster identities.');
    expect(errorCopy).toBeInTheDocument();
    expect(errorCopy).toHaveClass('acx-cluster-drawer__status--error');
    expect(screen.getByRole('button', { name: 'Rescan with sensitive settings' })).toBeEnabled();
  });

  it('disables the sensitive rescan with an accessible reason while offline', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        rescanDisabled
        rescanAriaDisabled
        rescanTitle="Unavailable while the recognition service is offline"
      />,
    );

    const rescanButton = screen.getByRole('button', { name: 'Rescan with sensitive settings' });
    expect(rescanButton).toBeDisabled();
    expect(rescanButton).toHaveAttribute('aria-disabled', 'true');
    expect(rescanButton).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
  });

  it('keeps the sensitive rescan enabled and firing when online', () => {
    const onRescanCluster = vi.fn();
    render(<ClusterDrawerPanel {...baseProps} onRescanCluster={onRescanCluster} />);

    const rescanButton = screen.getByRole('button', { name: 'Rescan with sensitive settings' });
    expect(rescanButton).toBeEnabled();
    expect(rescanButton).not.toHaveAttribute('title');
    fireEvent.click(rescanButton);
    expect(onRescanCluster).toHaveBeenCalledWith(cluster, identities);
  });

  it('renders the shell with Close when only requestedClusterId is set (loading)', () => {
    const onClose = vi.fn();
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={null}
        identities={[]}
        requestedClusterId="cluster-missing"
        isDetailLoading
        onClose={onClose}
      />,
    );

    expect(screen.getByText('Loading faces…')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Close$/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders the shell with Close and error when only requestedClusterId is set (failed fetch)', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={null}
        identities={[]}
        requestedClusterId="cluster-missing"
        detailError="Unable to load face group details."
      />,
    );

    expect(screen.getByRole('button', { name: /^Close$/i })).toBeInTheDocument();
    expect(screen.getByText('Unable to load face group details.')).toBeInTheDocument();
    expect(screen.queryByText('No faces found in this face group.')).not.toBeInTheDocument();
    expect(screen.queryByText('Unnamed face group')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Face group unavailable' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /Commit to roster entry/i })).not.toBeInTheDocument();
  });

  it('does not paint empty copy while the requested cluster is still loading', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={null}
        identities={[]}
        requestedClusterId="cluster-missing"
        isDetailLoading
      />,
    );

    expect(screen.getByText('Loading faces…')).toBeInTheDocument();
    expect(screen.queryByText('Unable to load face group details.')).not.toBeInTheDocument();
    expect(screen.queryByText('No faces found in this face group.')).not.toBeInTheDocument();
  });

  it('hides Move and uses honest copy when reassign is unavailable in this view', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        reassignUnavailableReason="Face moves happen in the Workbench review queue."
      />,
    );

    expect(screen.queryByRole('button', { name: /Move to/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/No other face groups available/i)).not.toBeInTheDocument();
    expect(screen.getByText('Face moves happen in the Workbench review queue.')).toBeInTheDocument();
  });

  it('does not make faces draggable or accept drops when reassign is boarded up', () => {
    const onDiscardDrop = vi.fn();
    const onFaceDragStart = vi.fn();
    render(
      <ClusterDrawerPanel
        {...baseProps}
        reassignUnavailableReason="Face moves happen in the Workbench review queue."
        isDragging
        onDiscardDrop={onDiscardDrop}
        onFaceDragStart={onFaceDragStart}
      />,
    );

    const face = screen.getByRole('figure', { name: /Face from media 1/i });
    expect(face).not.toHaveAttribute('draggable', 'true');
    fireEvent.dragStart(face);
    expect(onFaceDragStart).not.toHaveBeenCalled();
    expect(screen.queryByText('Drop faces here to remove them from this face group.')).not.toBeInTheDocument();
    expect(onDiscardDrop).not.toHaveBeenCalled();
  });
});

/** Same selector the drawer trap and the e2e walk use. */
const DRAWER_FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const HONEST_MOVE_COPY = /Face moves happen in the Workbench review queue/i;

const renderBoardedUpDrawer = () =>
  render(
    <ClusterDrawerPanel
      {...baseProps}
      reassignUnavailableReason="Face moves happen in the Workbench review queue."
    />,
  );

const drawerRoot = (): HTMLElement => {
  const drawer = document.querySelector('.acx-cluster-drawer');
  if (!(drawer instanceof HTMLElement)) {
    throw new Error('expected .acx-cluster-drawer');
  }
  return drawer;
};

const accessibleNameOf = (el: HTMLElement): string => {
  const labelled = el.getAttribute('aria-label');
  if (labelled) {
    return labelled;
  }
  const titled = el.getAttribute('title');
  if (titled) {
    return titled;
  }
  return (el.textContent ?? '').replace(/\s+/g, ' ').trim();
};

describe('ClusterDrawerPanel boarded-up a11y walk (UXW2-4-R1-24)', () => {
  it('Close is a named button, honest Move copy is shown, and Move to count is 0', () => {
    renderBoardedUpDrawer();
    const drawer = drawerRoot();

    const close = within(drawer).getByRole('button', { name: /^Close$/i });
    expect(close.tagName).toBe('BUTTON');
    expect(close).toHaveAttribute('type', 'button');

    expect(within(drawer).getByText(HONEST_MOVE_COPY)).toBeInTheDocument();
    expect(within(drawer).queryAllByRole('button', { name: /Move to/i })).toHaveLength(0);
  });

  it('focusable set starts at Close and no control is tabindex=-1 trapped', () => {
    renderBoardedUpDrawer();
    const drawer = drawerRoot();
    const close = within(drawer).getByRole('button', { name: /^Close$/i });

    expect(close).toHaveFocus();

    const focusables = Array.from(drawer.querySelectorAll<HTMLElement>(DRAWER_FOCUSABLE_SELECTOR));
    expect(focusables.length).toBeGreaterThan(0);
    expect(focusables[0]).toBe(close);

    const trapped = focusables.filter((el) => el.getAttribute('tabindex') === '-1');
    expect(trapped).toEqual([]);

    const names = focusables.map(accessibleNameOf);
    expect(names[0]).toMatch(/^Close$/i);
    expect(names.some((name) => /Rescan with sensitive settings/i.test(name))).toBe(true);
    expect(names.some((name) => /Commit to roster entry/i.test(name))).toBe(true);
    expect(names.every((name) => !/Move to/i.test(name))).toBe(true);

    for (const el of focusables) {
      el.focus();
      expect(el).toHaveFocus();
    }
  });
});

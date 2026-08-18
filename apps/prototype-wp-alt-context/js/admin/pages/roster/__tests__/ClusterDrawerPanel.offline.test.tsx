import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
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
});

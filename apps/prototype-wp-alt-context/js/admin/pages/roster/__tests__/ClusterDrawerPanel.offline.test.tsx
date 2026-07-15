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

describe('ClusterDrawerPanel rescan offline gate (RES-15, A11Y-24)', () => {
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

import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterIdentity, ClusterSummary } from '../../../api/recognition';
import { toRosterPerson } from '../../../navigation/appLinks';
import { ClusterDrawerPanel } from '../ClusterDrawerPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[ds]|%\d+\$[ds]/g, () => String(args[i++]));
  },
}));

const identities: ClusterIdentity[] = [
  {
    identity_id: 'identity-1',
    media_id: 1,
    similarity: 0.9,
    confidence: 0.9,
    bbox: null,
  },
];

const makeCluster = (overrides: Partial<ClusterSummary> = {}): ClusterSummary => ({
  id: 'cluster-1',
  label: 'Alex Rivera',
  identity_count: 3,
  member_ids: ['identity-1'],
  representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 100, height: 100 } },
  sample_identities: [],
  ...overrides,
});

const baseProps = {
  identities,
  mediaMap: {},
  onClose: () => undefined,
  onRescanCluster: vi.fn(),
  isRescanning: false,
  onCommitCluster: () => undefined,
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

describe('ClusterDrawerPanel person-aware states (E15-17 S4)', () => {
  it('assigned cluster: Open person review deep-links to the roster person workspace', async () => {
    const user = userEvent.setup();
    const onOpenPersonWorkspace = vi.fn();
    const personUuid = 'person-uuid-assigned';

    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={makeCluster({ person_uuid: personUuid, identity_count: 4 })}
        onOpenPersonWorkspace={onOpenPersonWorkspace}
      />,
    );

    const reviewLink = screen.getByRole('link', { name: 'Open person review' });
    expect(reviewLink).toHaveAttribute('href', toRosterPerson(personUuid));
    expect(screen.queryByRole('button', { name: 'Open person workspace' })).not.toBeInTheDocument();

    await user.click(reviewLink);
    expect(onOpenPersonWorkspace).toHaveBeenCalledWith(personUuid);
  });

  it('unresolved cluster: review mode without inventing a person link', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={makeCluster({ person_uuid: null, identity_count: 3, label: null })}
        onOpenPersonWorkspace={vi.fn()}
      />,
    );

    expect(screen.getByText('Unresolved cluster')).toBeInTheDocument();
    expect(screen.getByLabelText('Commit to roster entry')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open person review' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Open person/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Singleton proposal')).not.toBeInTheDocument();
  });

  it('singleton proposal: honest proposal state, no invented person link', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={makeCluster({ person_uuid: null, identity_count: 1, label: null })}
        onOpenPersonWorkspace={vi.fn()}
      />,
    );

    expect(screen.getByText('Singleton proposal')).toBeInTheDocument();
    expect(
      screen.getByText('This face group is a proposal, not a curated person. Review it before assigning.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Commit to roster entry')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open person review' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Open person/i })).not.toBeInTheDocument();
  });
});

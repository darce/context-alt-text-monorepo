import React from 'react';
import { createEvent, fireEvent, render, screen } from '@testing-library/react';
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

    expect(screen.getByText('Assigned cluster')).toBeInTheDocument();
    const reviewLink = screen.getByRole('link', { name: 'Open person review' });
    expect(reviewLink).toHaveAttribute('href', `#/roster?person=${personUuid}`);
    expect(screen.queryByRole('button', { name: 'Open person workspace' })).not.toBeInTheDocument();
    expect(screen.queryByText('Singleton proposal')).not.toBeInTheDocument();

    await user.click(reviewLink);
    expect(onOpenPersonWorkspace).toHaveBeenCalledWith(personUuid);
  });

  it('plain left-click prevents native hash navigation and opens the workspace', () => {
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
    const event = createEvent.click(reviewLink);
    fireEvent(reviewLink, event);

    expect(event.defaultPrevented).toBe(true);
    expect(onOpenPersonWorkspace).toHaveBeenCalledWith(personUuid);
  });

  it('modifier-clicks keep the href path and do not mutate the current tab', () => {
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
    fireEvent.click(reviewLink, { metaKey: true });
    fireEvent.click(reviewLink, { ctrlKey: true });
    fireEvent.click(reviewLink, { shiftKey: true });
    fireEvent.click(reviewLink, { altKey: true });

    expect(onOpenPersonWorkspace).not.toHaveBeenCalled();
    expect(reviewLink).toHaveAttribute('href', `#/roster?person=${personUuid}`);
  });

  it.each(['', ' '])('person_uuid %j is Unresolved with no person review link', (personUuid) => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={makeCluster({ person_uuid: personUuid, identity_count: 3, label: null })}
        onOpenPersonWorkspace={vi.fn()}
      />,
    );

    expect(screen.getByText('Unresolved cluster')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open person review' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Open person/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Singleton proposal')).not.toBeInTheDocument();
  });

  it('assigned cluster with identity_count 1 is Assigned, not a singleton proposal', () => {
    const personUuid = 'person-uuid-singleton-assigned';

    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={makeCluster({ person_uuid: personUuid, identity_count: 1 })}
        onOpenPersonWorkspace={vi.fn()}
      />,
    );

    expect(screen.getByText('Assigned cluster')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open person review' })).toHaveAttribute(
      'href',
      `#/roster?person=${personUuid}`,
    );
    expect(screen.queryByText('Singleton proposal')).not.toBeInTheDocument();
  });

  it('identity_count 0 stale projection is Unresolved, not a singleton proposal', () => {
    render(
      <ClusterDrawerPanel
        {...baseProps}
        cluster={makeCluster({ person_uuid: null, identity_count: 0, label: null })}
        onOpenPersonWorkspace={vi.fn()}
      />,
    );

    expect(screen.getByText('Unresolved cluster')).toBeInTheDocument();
    expect(screen.queryByText('Singleton proposal')).not.toBeInTheDocument();
    expect(
      screen.queryByText('This face group is a proposal, not a curated person. Review it before assigning.'),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open person review' })).not.toBeInTheDocument();
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

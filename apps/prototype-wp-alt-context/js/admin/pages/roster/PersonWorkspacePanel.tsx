import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';

const QUEUE_SECTIONS = [
  {
    id: 'singleton-proposals',
    label: __('Singleton proposals', 'alt-context'),
  },
  {
    id: 'hard-examples',
    label: __('Hard examples', 'alt-context'),
  },
  {
    id: 'needs-confirmation-after-merge',
    label: __('Needs confirmation after merge', 'alt-context'),
  },
] as const;

interface PersonWorkspacePanelProps {
  entry: RosterEntry;
}

export const PersonWorkspacePanel = ({ entry }: PersonWorkspacePanelProps): React.JSX.Element => {
  const queueMemberships = new Set(entry.queue_memberships);

  return (
    <section
      className="acx-roster__person-workspace"
      role="region"
      aria-label={sprintf(__('Person workspace: %s', 'alt-context'), entry.name)}
    >
      <header className="acx-roster__person-workspace-header">
        <h3>{entry.name}</h3>
        <p className="acx-roster__person-workspace-meta">
          {sprintf(__('%d clusters assigned', 'alt-context'), entry.cluster_count)}
        </p>
      </header>

      <section aria-labelledby="acx-person-workspace-queues-title">
        <h4 id="acx-person-workspace-queues-title">{__('Curriculum review queues', 'alt-context')}</h4>
        <dl>
          {QUEUE_SECTIONS.map((queueSection) => {
            const isQueued = queueMemberships.has(queueSection.id);
            return (
              <div key={queueSection.id}>
                <dt>{queueSection.label}</dt>
                <dd>{isQueued ? __('Queued', 'alt-context') : __('Not queued', 'alt-context')}</dd>
              </div>
            );
          })}
        </dl>
      </section>
    </section>
  );
};

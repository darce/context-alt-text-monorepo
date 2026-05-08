import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';

interface PersonWorkspacePanelProps {
  entry: RosterEntry;
}

export const PersonWorkspacePanel = ({ entry }: PersonWorkspacePanelProps): React.JSX.Element => (
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
  </section>
);

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';

interface PersonWorkspacePanelProps {
  entry: RosterEntry;
}

const getProjectionStatusLabel = (entry: RosterEntry): string => {
  return typeof entry.projection_status === 'string' && entry.projection_status.length > 0
    ? entry.projection_status
    : __('unknown', 'alt-context');
};

const getProjectionRefreshedAtLabel = (entry: RosterEntry): string => {
  return typeof entry.projection_refreshed_at === 'string' && entry.projection_refreshed_at.length > 0
    ? entry.projection_refreshed_at
    : __('Unavailable', 'alt-context');
};

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
      <p className="acx-roster__person-workspace-meta">
        {sprintf(__('Projection status: %s', 'alt-context'), getProjectionStatusLabel(entry))}
      </p>
      <p className="acx-roster__person-workspace-meta">
        {sprintf(__('Projection refreshed: %s', 'alt-context'), getProjectionRefreshedAtLabel(entry))}
      </p>
      <p className="acx-roster__person-workspace-meta">
        {sprintf(__('Source version: %d', 'alt-context'), entry.source_version)}
      </p>
    </header>
  </section>
);

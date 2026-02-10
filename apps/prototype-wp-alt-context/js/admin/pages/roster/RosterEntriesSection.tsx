import React from 'react';
import { __ } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import { RosterEntriesTable } from './RosterEntriesTable';

export interface RosterEntriesQuery {
  isLoading: boolean;
  isError: boolean;
  data?: RosterEntry[];
  refetch: () => unknown;
}

export interface RosterEntriesSectionProps {
  query: RosterEntriesQuery;
}

export const RosterEntriesSection = ({ query }: RosterEntriesSectionProps): React.JSX.Element => {
  if (query.isLoading) {
    return <p>{__('Loading roster entries…', 'alt-context')}</p>;
  }

  if (query.isError) {
    return (
      <div>
        <p>{__('Unable to load roster entries.', 'alt-context')}</p>
        <button type="button" onClick={() => void query.refetch()}>
          {__('Retry', 'alt-context')}
        </button>
      </div>
    );
  }

  return <RosterEntriesTable entries={query.data ?? []} />;
};

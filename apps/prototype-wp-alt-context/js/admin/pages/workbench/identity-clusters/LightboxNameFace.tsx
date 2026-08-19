/**
 * Lightbox-anchored naming (UXW2-6 slice 2). Same NameFaceControl + person-commit
 * resolution as the queue card; the commit applies to the reviewed item's group.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import { listRosterEntries } from '../../../api/rosterApi';
import { NameFaceControl, type NameFaceResolution } from './NameFaceControl';
import { buildNamingOptions } from './buildNamingOptions';
import { getReservedLabelMessage, isReservedLabel } from './reservedLabel';
import {
  PERSON_COMMIT_PHASE,
  type PersonCommitPhase,
  type PersonCommitRequest,
} from './useSuggestionReviewMutations';

export const LIGHTBOX_NAME_SAVED_ANNOUNCE = __(
  "Name saved for this person's review group.",
  'alt-context',
);

export interface LightboxNameFaceProps {
  clusterId: string;
  phase: PersonCommitPhase;
  errorMessage: string | null;
  disabled?: boolean;
  onCommit: (request: PersonCommitRequest) => void;
  onCancel: () => void;
  onRetry: () => void;
}

export const LightboxNameFace = ({
  clusterId,
  phase,
  errorMessage,
  disabled = false,
  onCommit,
  onCancel,
  onRetry,
}: LightboxNameFaceProps): React.JSX.Element => {
  const [draft, setDraft] = React.useState('');
  const [reservedError, setReservedError] = React.useState<string | null>(null);
  const isBusy = phase === PERSON_COMMIT_PHASE.COMMITTING || disabled;

  const rosterQuery = useQuery({
    queryKey: queryKeys.roster.entries(),
    queryFn: () => listRosterEntries(),
    staleTime: 30_000,
  });

  const options = React.useMemo(
    () =>
      buildNamingOptions({
        rosterEntries: rosterQuery.data ?? [],
        labelMatches: [],
        limit: null,
      }).options.map((option) => ({
        value: option.value,
        label: option.label,
        source: option.source,
      })),
    [rosterQuery.data],
  );

  const handleValueChange = (value: string): void => {
    setReservedError(null);
    setDraft(value);
  };

  const handleCommitResolution = (resolution: NameFaceResolution): void => {
    if (isBusy || rosterQuery.isLoading || rosterQuery.isError) {
      return;
    }
    if (resolution.kind === 'ambiguous') {
      return;
    }
    if (resolution.kind === 'roster') {
      setReservedError(null);
      onCommit({ clusterId, rosterEntryId: resolution.rosterEntryId });
      return;
    }
    if (isReservedLabel(resolution.name)) {
      setReservedError(getReservedLabelMessage());
      return;
    }
    setReservedError(null);
    onCommit({ clusterId, newEntryName: resolution.name });
  };

  return (
    <div className="acx-review-card-lightbox__naming" data-testid="acx-lightbox-name-face">
      {rosterQuery.isError ? (
        <div className="acx-person-commit__failure" role="alert">
          <p className="acx-person-commit__failure-message">
            {__('Unable to load people. Retry before naming someone new.', 'alt-context')}
          </p>
          <button
            type="button"
            className="button acx-person-commit__retry"
            onClick={() => {
              void rosterQuery.refetch();
            }}
            disabled={isBusy}
          >
            {__('Retry', 'alt-context')}
          </button>
        </div>
      ) : (
        <NameFaceControl
          options={options}
          value={draft}
          onValueChange={handleValueChange}
          onCommit={handleCommitResolution}
          onCancel={onCancel}
          isPending={phase === PERSON_COMMIT_PHASE.COMMITTING}
          isLoading={rosterQuery.isLoading}
          disabled={disabled || rosterQuery.isError}
          commitLabel={__('Save name', 'alt-context')}
          pendingLabel={__('Saving name…', 'alt-context')}
          previewCommit
          placeholder={__('Type a name…', 'alt-context')}
          searchPlaceholder={__('Type a name…', 'alt-context')}
          visibleLabel={__('Name this person', 'alt-context')}
          inputId={`acx-lightbox-name-${clusterId}`}
          autoFocus
          suggestionsHeader={__('People', 'alt-context')}
          commitButtonClassName="button button-primary acx-person-commit__confirm"
          className="acx-person-commit__controls"
          classPrefix="acx-person-commit"
        />
      )}

      {reservedError ? (
        <p className="acx-person-commit__failure-message" role="alert">
          {reservedError}
        </p>
      ) : null}

      {phase === PERSON_COMMIT_PHASE.FAILED ? (
        <div className="acx-person-commit__failure" role="alert">
          <p className="acx-person-commit__failure-message">
            {errorMessage ?? __('Could not save the name. Retry to try again.', 'alt-context')}
          </p>
          <button
            type="button"
            className="button acx-person-commit__retry"
            onClick={onRetry}
            disabled={isBusy}
          >
            {__('Retry', 'alt-context')}
          </button>
        </div>
      ) : null}
    </div>
  );
};

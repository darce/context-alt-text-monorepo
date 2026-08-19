/**
 * E21-5 Slice 3 — roster person-commit chrome for the review card.
 *
 * UXW2-3: single-gesture naming via NameFaceControl — inline text input with
 * roster typeahead; Enter or "Save name" commits. Exact roster match binds
 * (rosterEntryId); a novel name creates the person (newEntryName) — creation
 * is the default outcome. Success: "View in roster →" deep-links the person.
 * Failure: persistent role=alert + retry.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import { listRosterEntries } from '../../../api/rosterApi';
import { NameFaceControl, type NameFaceResolution } from './NameFaceControl';
import { namingOptionValue } from './buildNamingOptions';
import { viewInRosterHref } from './personCommitCopy';
import { getReservedLabelMessage, isReservedLabel } from './reservedLabel';
import {
  PERSON_COMMIT_PHASE,
  type PersonCommitPhase,
  type PersonCommitRequest,
} from './useSuggestionReviewMutations';

export interface PersonCommitControlProps {
  clusterId: string;
  /** When true, person-commit is the card's primary naming action (NAME/CLUSTER). */
  isPrimary?: boolean;
  phase: PersonCommitPhase;
  errorMessage: string | null;
  /** Disable while a hold/commit is in flight elsewhere (single-in-flight). */
  disabled?: boolean;
  onCommit: (request: PersonCommitRequest) => void;
  onRetry: () => void;
  /** Optional prefilled create name (e.g. NAME suggestion). */
  suggestedCreateName?: string | null;
  /** Person uuid after a successful commit — drives the roster deep-link. */
  committedPersonUuid?: string | null;
  /**
   * §7 single accent primary: when this control is the card's primary (NAME/CLUSTER),
   * the commit button carries the `data-acx-accent-primary` marker + accent chrome
   * (COL-03). The success surface has no commit button; it is a transient post-commit
   * state as the card advances, so no marker is emitted there.
   */
  accentPrimary?: boolean;
}

export const PersonCommitControl = ({
  clusterId,
  isPrimary = false,
  phase,
  errorMessage,
  disabled = false,
  onCommit,
  onRetry,
  suggestedCreateName = null,
  committedPersonUuid = null,
  accentPrimary = false,
}: PersonCommitControlProps): React.JSX.Element => {
  const [draft, setDraft] = React.useState('');
  /** BR-59: reserved create-name rejection (inline, same role=alert pattern as commit failure). */
  const [reservedError, setReservedError] = React.useState<string | null>(null);
  const isBusy = phase === PERSON_COMMIT_PHASE.COMMITTING || disabled;
  const queryClient = useQueryClient();

  const rosterQuery = useQuery({
    queryKey: queryKeys.roster.entries(),
    queryFn: () => listRosterEntries(),
    staleTime: 30_000,
  });

  React.useEffect(() => {
    if (phase !== PERSON_COMMIT_PHASE.SUCCEEDED) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
  }, [phase, queryClient]);

  // Full roster for create-vs-bind (R1-07). Overlay budgets the display slice.
  const options = React.useMemo(
    () =>
      (rosterQuery.data ?? []).map((entry) => ({
        value: namingOptionValue('person', entry.id),
        label: entry.name,
        source: 'person' as const,
      })),
    [rosterQuery.data],
  );

  const boundPersonUuid = React.useMemo(() => {
    if (committedPersonUuid) {
      return committedPersonUuid;
    }
    const bound = (rosterQuery.data ?? []).find((entry) => entry.name === draft);
    return bound?.person_uuid ?? null;
  }, [committedPersonUuid, draft, rosterQuery.data]);

  // Prefill create path from a suggested name once per cluster (FORM-04).
  React.useEffect(() => {
    setReservedError(null);
    setDraft(suggestedCreateName?.trim() ?? '');
  }, [clusterId, suggestedCreateName]);

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

  if (phase === PERSON_COMMIT_PHASE.SUCCEEDED) {
    return (
      <div
        className="acx-person-commit acx-person-commit--success"
        data-testid="acx-person-commit"
        data-person-commit-primary={isPrimary ? 'true' : 'false'}
      >
        <p className="acx-person-commit__success-message" role="status">
          {__('Name saved.', 'alt-context')}
        </p>
        <a className="acx-person-commit__roster-link" href={viewInRosterHref(boundPersonUuid)}>
          {__('View in roster →', 'alt-context')}
        </a>
      </div>
    );
  }

  return (
    <div
      className={`acx-person-commit${isPrimary ? ' acx-person-commit--primary' : ''}`}
      data-testid="acx-person-commit"
      data-person-commit-primary={isPrimary ? 'true' : 'false'}
    >
      <p className="acx-person-commit__disclosure">
        {__(
          'Suggested by face matching based on similarity — confirm before treating it as fact.',
          'alt-context',
        )}
      </p>

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
          isPending={phase === PERSON_COMMIT_PHASE.COMMITTING}
          isLoading={rosterQuery.isLoading}
          disabled={disabled || rosterQuery.isError}
          commitLabel={__('Save name', 'alt-context')}
          pendingLabel={__('Saving name…', 'alt-context')}
          placeholder={__('Type a name…', 'alt-context')}
          searchPlaceholder={__('Type a name…', 'alt-context')}
          ariaLabel={__('Name this person', 'alt-context')}
          inputId={`acx-person-commit-${clusterId}`}
          autoFocus={false}
          accentPrimary={isPrimary && accentPrimary}
          suggestionsHeader={__('People', 'alt-context')}
          commitButtonClassName={
            isPrimary
              ? accentPrimary
                ? 'button button-primary acx-person-commit__confirm acx-accent-primary-action'
                : 'button button-primary acx-person-commit__confirm'
              : 'button acx-person-commit__confirm'
          }
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

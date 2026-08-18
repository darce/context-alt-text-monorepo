/**
 * E21-5 Slice 3 — roster person-commit chrome for the review card.
 *
 * UXW2-3: single-gesture naming via NameFaceControl — inline text input with
 * roster typeahead; Enter or "Save name" commits. Exact roster match binds
 * (rosterEntryId); a novel name creates the person (newEntryName) — creation
 * is the default outcome. Success: generic "View in roster →" (#/roster).
 * Failure: persistent role=alert + retry.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import { listRosterEntries } from '../../../api/rosterApi';
import { NameFaceControl, type NameFaceResolution } from './NameFaceControl';
import { namingOptionValue } from './buildNamingOptions';
import {
  MODEL_OUTPUT_DISCLOSURE,
  PERSON_COMMIT_COMBOBOX_ARIA,
  PERSON_COMMIT_COMMITTING_COPY,
  PERSON_COMMIT_CONFIRM_COPY,
  PERSON_COMMIT_FAILURE_COPY,
  PERSON_COMMIT_PLACEHOLDER,
  PERSON_COMMIT_SUCCESS_COPY,
  VIEW_IN_ROSTER_COPY,
  VIEW_IN_ROSTER_HREF,
} from './personCommitCopy';
import { isReservedLabel, RESERVED_LABEL_MESSAGE } from './reservedLabel';
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
  accentPrimary = false,
}: PersonCommitControlProps): React.JSX.Element => {
  const [draft, setDraft] = React.useState('');
  /** BR-59: reserved create-name rejection (inline, same role=alert pattern as commit failure). */
  const [reservedError, setReservedError] = React.useState<string | null>(null);
  const isBusy = phase === PERSON_COMMIT_PHASE.COMMITTING || disabled;

  const rosterQuery = useQuery({
    queryKey: queryKeys.roster.entries(),
    queryFn: () => listRosterEntries(),
    staleTime: 30_000,
  });

  // Roster typeahead: prefix-filter against the typed draft (COG-02 recognition).
  const options = React.useMemo(() => {
    const filter = draft.trim().toLowerCase();
    return (rosterQuery.data ?? [])
      .filter((entry) => !filter || entry.name.toLowerCase().startsWith(filter))
      .map((entry) => ({
        value: namingOptionValue('person', entry.id),
        label: entry.name,
        source: 'person' as const,
      }));
  }, [rosterQuery.data, draft]);

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
    if (isBusy) {
      return;
    }
    if (resolution.kind === 'roster') {
      setReservedError(null);
      onCommit({ clusterId, rosterEntryId: resolution.rosterEntryId });
      return;
    }
    // BR-59: reject reserved machine-shaped create names before POST.
    if (isReservedLabel(resolution.name)) {
      setReservedError(__(RESERVED_LABEL_MESSAGE, 'alt-context'));
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
          {__(PERSON_COMMIT_SUCCESS_COPY, 'alt-context')}
        </p>
        <a className="acx-person-commit__roster-link" href={VIEW_IN_ROSTER_HREF}>
          {__(VIEW_IN_ROSTER_COPY, 'alt-context')}
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
      <p className="acx-person-commit__disclosure">{__(MODEL_OUTPUT_DISCLOSURE, 'alt-context')}</p>

      <NameFaceControl
        options={options}
        value={draft}
        onValueChange={handleValueChange}
        onCommit={handleCommitResolution}
        isPending={phase === PERSON_COMMIT_PHASE.COMMITTING}
        disabled={disabled}
        commitLabel={__(PERSON_COMMIT_CONFIRM_COPY, 'alt-context')}
        pendingLabel={__(PERSON_COMMIT_COMMITTING_COPY, 'alt-context')}
        placeholder={__(PERSON_COMMIT_PLACEHOLDER, 'alt-context')}
        ariaLabel={__(PERSON_COMMIT_COMBOBOX_ARIA, 'alt-context')}
        inputId={`acx-person-commit-${clusterId}`}
        autoFocus={false}
        accentPrimary={isPrimary && accentPrimary}
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

      {reservedError ? (
        <p className="acx-person-commit__failure-message" role="alert">
          {reservedError}
        </p>
      ) : null}

      {phase === PERSON_COMMIT_PHASE.FAILED ? (
        <div className="acx-person-commit__failure" role="alert">
          <p className="acx-person-commit__failure-message">
            {errorMessage ?? __(PERSON_COMMIT_FAILURE_COPY, 'alt-context')}
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

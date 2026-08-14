/**
 * E21-5 Slice 3 — roster person-commit chrome for the review card.
 *
 * Creatable combobox → commitClusterToRosterEntry (not updateClusterLabel).
 * Success: generic "View in roster →" (#/roster). Failure: persistent role=alert + retry.
 * Tertiary "just label" routes open_label via onJustLabel.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useQuery } from '@tanstack/react-query';

import { Combobox } from '../../../../components/ui/combobox';
import { queryKeys } from '../../../api/queryKeys';
import { listRosterEntries } from '../../../api/rosterApi';
import {
  JUST_LABEL_COPY,
  MODEL_OUTPUT_DISCLOSURE,
  PERSON_COMMIT_COMBOBOX_ARIA,
  PERSON_COMMIT_COMMITTING_COPY,
  PERSON_COMMIT_CONFIRM_COPY,
  PERSON_COMMIT_CREATE_NEW_COPY,
  PERSON_COMMIT_FAILURE_COPY,
  PERSON_COMMIT_PLACEHOLDER,
  PERSON_COMMIT_SUCCESS_COPY,
  VIEW_IN_ROSTER_COPY,
  VIEW_IN_ROSTER_HREF,
} from './personCommitCopy';
import { isHumanLabeledTarget } from './suggestionProjection';
import {
  PERSON_COMMIT_PHASE,
  type PersonCommitPhase,
  type PersonCommitRequest,
} from './useSuggestionReviewMutations';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

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
  onJustLabel?: (clusterId: string) => void;
  /** Optional prefilled create name (e.g. NAME suggestion). */
  suggestedCreateName?: string | null;
  /**
   * §7 single accent primary: when this control is the card's primary (NAME/CLUSTER),
   * the Confirm button carries the `data-acx-accent-primary` marker + accent chrome
   * (COL-03). The success surface has no Confirm; it is a transient post-commit state
   * as the card advances, so no marker is emitted there.
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
  onJustLabel,
  suggestedCreateName = null,
  accentPrimary = false,
}: PersonCommitControlProps): React.JSX.Element => {
  const [selectedEntryId, setSelectedEntryId] = React.useState('');
  const [newEntryName, setNewEntryName] = React.useState('');
  /** BR-35: live combobox search draft for the always-available create action. */
  const [draftInput, setDraftInput] = React.useState('');
  /** BR-59: reserved create-name rejection (inline, same role=alert pattern as commit failure). */
  const [reservedError, setReservedError] = React.useState<string | null>(null);
  const isBusy = phase === PERSON_COMMIT_PHASE.COMMITTING || disabled;

  const reservedLabelMessage = __(
    'This label format is reserved for automatic cluster IDs. Choose a descriptive name.',
    'alt-context',
  );

  const rosterQuery = useQuery({
    queryKey: queryKeys.roster.entries(),
    queryFn: () => listRosterEntries(),
    staleTime: 30_000,
  });

  const rosterEntries = rosterQuery.data ?? [];

  // Prefill create path from a suggested name once per cluster.
  React.useEffect(() => {
    setSelectedEntryId('');
    setNewEntryName('');
    setDraftInput('');
    setReservedError(null);
    const trimmed = suggestedCreateName?.trim() ?? '';
    if (trimmed.length > 0) {
      setSelectedEntryId('create');
      setNewEntryName(trimmed);
      setDraftInput(trimmed);
    }
  }, [clusterId, suggestedCreateName]);

  const handleCreate = (name: string): void => {
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }
    setReservedError(null);
    setSelectedEntryId('create');
    setNewEntryName(trimmed);
    setDraftInput(trimmed);
  };

  const handleSelectEntry = (nextValue: string): void => {
    setReservedError(null);
    setSelectedEntryId(nextValue);
    if (nextValue !== 'create') {
      setNewEntryName('');
    }
  };

  const isCreatingEntry = selectedEntryId === 'create';
  const canCommit =
    !isBusy &&
    ((isCreatingEntry && newEntryName.trim().length > 0) ||
      (!isCreatingEntry && selectedEntryId !== ''));

  const createCandidate = (isCreatingEntry ? newEntryName : draftInput).trim();
  const exactRosterMatch = rosterEntries.some(
    (entry) => entry.name.trim().toLowerCase() === createCandidate.toLowerCase(),
  );
  // BR-35: always offer create when typed name is non-empty and not an exact match
  // (shared combobox only surfaces Create on zero substring matches).
  const showExplicitCreate =
    !isBusy && createCandidate.length > 0 && !exactRosterMatch && !isCreatingEntry;

  const handleConfirm = (): void => {
    if (!canCommit) {
      return;
    }
    if (isCreatingEntry) {
      const trimmed = newEntryName.trim();
      // BR-59: reject reserved machine-shaped create names before POST.
      if (!isHumanLabeledTarget(trimmed)) {
        setReservedError(reservedLabelMessage);
        return;
      }
      setReservedError(null);
      onCommit({ clusterId, newEntryName: trimmed });
      return;
    }
    setReservedError(null);
    onCommit({ clusterId, rosterEntryId: Number.parseInt(selectedEntryId, 10) });
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

      <div className="acx-person-commit__controls">
        <Combobox
          options={rosterEntries.map((entry) => ({
            value: entry.id.toString(),
            label: entry.name,
          }))}
          value={isCreatingEntry ? newEntryName : selectedEntryId}
          onSelect={handleSelectEntry}
          onCreate={handleCreate}
          onValueChange={setDraftInput}
          ariaLabel={__(PERSON_COMMIT_COMBOBOX_ARIA, 'alt-context')}
          placeholder={__(PERSON_COMMIT_PLACEHOLDER, 'alt-context')}
          className="acx-person-commit__combobox"
          id={`acx-person-commit-${clusterId}`}
          disabled={isBusy}
          isLoading={rosterQuery.isLoading}
        />

        <button
          type="button"
          className={
            isPrimary
              ? accentPrimary
                ? 'button button-primary acx-person-commit__confirm acx-accent-primary-action'
                : 'button button-primary acx-person-commit__confirm'
              : 'button acx-person-commit__confirm'
          }
          onClick={handleConfirm}
          disabled={!canCommit}
          {...(isPrimary && accentPrimary ? { [ACCENT_PRIMARY_ATTR]: true } : {})}
        >
          {phase === PERSON_COMMIT_PHASE.COMMITTING
            ? __(PERSON_COMMIT_COMMITTING_COPY, 'alt-context')
            : __(PERSON_COMMIT_CONFIRM_COPY, 'alt-context')}
        </button>
      </div>

      {showExplicitCreate ? (
        <button
          type="button"
          className="button button-link acx-person-commit__create-new"
          onClick={() => handleCreate(createCandidate)}
          disabled={isBusy}
        >
          {sprintf(__(PERSON_COMMIT_CREATE_NEW_COPY, 'alt-context'), createCandidate)}
        </button>
      ) : null}

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

      {onJustLabel ? (
        <button
          type="button"
          className="button button-link acx-person-commit__just-label"
          onClick={() => onJustLabel(clusterId)}
          disabled={isBusy}
        >
          {__(JUST_LABEL_COPY, 'alt-context')}
        </button>
      ) : null}
    </div>
  );
};

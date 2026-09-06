import React, { useEffect, useRef, useState } from 'react';

import {
  GUIDED_CANDIDATE_STATUS,
  GUIDED_IDENTITY_STATUS,
  confirmedPersonKeys,
  getLastGuidedApplication,
} from '../../guidedPrototype/state';
import type { GuidedCandidateStatus, GuidedScenario } from '../../guidedPrototype/state';

export interface GuidedDescriptionReviewProps {
  scenario: GuidedScenario;
  resetVersion: number;
  onSaveEdit: (text: string) => string | undefined;
  onReject: () => void;
  onApply: () => void;
  onUndo: () => void;
}

const candidateStatusLabel = (status: GuidedCandidateStatus): string => {
  if (status === GUIDED_CANDIDATE_STATUS.EDITED) {
    return 'Edited by you';
  }
  if (status === GUIDED_CANDIDATE_STATUS.REJECTED) {
    return 'Rejected. The saved text did not change';
  }
  return 'Ready for you to check';
};

const descriptionExplanation = (scenario: GuidedScenario): string => {
  const confirmedKeys = confirmedPersonKeys(scenario);
  const allMatchesDecided = scenario.identities.every(
    (identity) => identity.status !== GUIDED_IDENTITY_STATUS.UNCONFIRMED,
  );

  if (confirmedKeys.length === 2) {
    return 'You confirmed both matches, so both names are in the draft. The visual details and page context stay the same.';
  }

  if (confirmedKeys.length === 1) {
    return 'You confirmed one match, so one name is in the draft. The other person is described, not named.';
  }

  if (allMatchesDecided) {
    return 'You kept both people unnamed, so the draft only says what is visible.';
  }

  return 'Decide each face match first: confirm it, or keep the person unnamed. Until then the draft only says what is visible.';
};

export const GuidedDescriptionReview = ({
  scenario,
  resetVersion,
  onSaveEdit,
  onReject,
  onApply,
  onUndo,
}: GuidedDescriptionReviewProps): React.JSX.Element => {
  const [editValue, setEditValue] = useState(scenario.candidate.text);
  const [editError, setEditError] = useState('');
  const editorRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setEditValue(scenario.candidate.text);
    setEditError('');
  }, [scenario.candidate.text, resetVersion]);

  const appliedEvent = getLastGuidedApplication(scenario.history);
  const hasUnsavedEdit = editValue !== scenario.candidate.text;
  const unsavedEditReasonId = 'guided-description-unsaved-reason';

  const handleSaveEdit = (): void => {
    if (editValue.trim() === '') {
      setEditError('A description cannot be empty.');
      editorRef.current?.focus();
      return;
    }

    const saveError = onSaveEdit(editValue);
    if (saveError) {
      setEditError(saveError);
      editorRef.current?.focus();
      return;
    }

    setEditError('');
  };

  const handleDiscardEdit = (): void => {
    setEditValue(scenario.candidate.text);
    setEditError('');
    editorRef.current?.focus();
  };

  return (
    <section className="acx-guided-review" aria-labelledby="acx-guided-review-title">
      <header className="acx-guided-review__header">
        <div>
          <p className="acx-guided-review__eyebrow">The description</p>
          <h2 id="acx-guided-review-title">Check the description before anything changes</h2>
        </div>
        <span className={`acx-guided-review__status acx-guided-review__status--${scenario.candidate.status}`}>
          {candidateStatusLabel(scenario.candidate.status)}
        </span>
      </header>

      <div className="acx-guided-review__context-grid">
        <div className="acx-guided-review__context-card">
          <h3 id="guided-visual-description-title">What the photo shows</h3>
          <ul>
            {scenario.visualFacts.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
          <p>
            Draft without names: <span>{scenario.drafts.none}</span>
          </p>
          <p>
            Alt text on the page right now: <span data-current-applied-text>{scenario.appliedText}</span>
          </p>
        </div>
        <div className="acx-guided-review__context-card">
          <h3 id="guided-page-context-title">The page</h3>
          <p>
            <strong>{scenario.pageContext.title}</strong>
          </p>
          <p>{scenario.pageContext.summary}</p>
        </div>
      </div>

      <section
        id="guided-section-review"
        className="acx-guided-review__comparison"
        aria-label="Review the description"
        data-testid="guided-candidate"
        tabIndex={-1}
      >
        <p className="acx-guided-review__explanation">{descriptionExplanation(scenario)}</p>
        <div>
          <h3>Without the names</h3>
          <p>{scenario.drafts.none}</p>
        </div>
        <div>
          <h3>Draft for you to check</h3>
          <p className="acx-guided-review__origin">This draft comes from a saved run, not a live one.</p>
          <label htmlFor="guided-description-draft">Description draft</label>
          <textarea
            ref={editorRef}
            id="guided-description-draft"
            aria-describedby={editError ? 'guided-description-draft-error' : undefined}
            aria-invalid={editError ? 'true' : undefined}
            value={editValue}
            rows={4}
            onChange={(event) => {
              setEditValue(event.target.value);
              setEditError('');
            }}
          />
          {editError ? (
            <p id="guided-description-draft-error" className="acx-guided-review__field-error" role="alert">
              {editError}
            </p>
          ) : null}
          {scenario.candidate.status === GUIDED_CANDIDATE_STATUS.REJECTED && !hasUnsavedEdit ? (
            <p className="acx-guided-review__rejected-notice">
              You rejected this draft, so Apply is off. Edit and save the text, or change an answer about a face, to get
              a new draft.
            </p>
          ) : null}
          {hasUnsavedEdit ? (
            <p id={unsavedEditReasonId} className="acx-guided-review__unsaved-notice">
              Unsaved edit. Save it before you apply, or discard it to go back to the saved draft.
            </p>
          ) : null}
          <div className="acx-guided-review__actions">
            <button type="button" className="acx-button acx-button--secondary" onClick={handleSaveEdit}>
              Save my edit
            </button>
            {hasUnsavedEdit ? (
              <button type="button" className="acx-button acx-button--tertiary" onClick={handleDiscardEdit}>
                Discard my edit
              </button>
            ) : null}
            <button
              type="button"
              className="acx-button acx-button--tertiary"
              onClick={onReject}
              disabled={scenario.candidate.status === GUIDED_CANDIDATE_STATUS.REJECTED}
            >
              Reject this draft
            </button>
          </div>
        </div>
      </section>

      <section
        id="guided-section-apply"
        className="acx-guided-review__apply"
        aria-label="Apply the description"
        tabIndex={-1}
      >
        <div>
          <h3>Apply it yourself</h3>
          <p>
            The practice copy says <strong data-applied-text>{scenario.appliedText}</strong>. Pressing Apply writes the
            saved draft to this practice copy only.
          </p>
          {hasUnsavedEdit ? (
            <p className="acx-guided-review__apply-reason" id="guided-apply-reason">
              Apply is off while your edit is unsaved. Save or discard it first.
            </p>
          ) : null}
        </div>
        <div className="acx-guided-review__actions">
          <button
            type="button"
            className="acx-button acx-button--primary"
            onClick={onApply}
            disabled={scenario.candidate.status === GUIDED_CANDIDATE_STATUS.REJECTED || hasUnsavedEdit}
            aria-describedby={hasUnsavedEdit ? 'guided-apply-reason' : undefined}
          >
            Apply to practice copy
          </button>
          <button
            type="button"
            className="acx-button acx-button--tertiary"
            onClick={onUndo}
            disabled={!appliedEvent}
          >
            Undo
          </button>
        </div>
      </section>
    </section>
  );
};

GuidedDescriptionReview.displayName = 'GuidedDescriptionReview';

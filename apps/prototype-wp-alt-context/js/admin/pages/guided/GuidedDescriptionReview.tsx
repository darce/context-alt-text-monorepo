import React, { useEffect, useRef, useState } from 'react';

import { getLastGuidedApplication, GUIDED_SCENARIO_ORIGIN_LABELS } from '../../guidedPrototype/state';
import type { GuidedCandidateStatus, GuidedIdentity, GuidedScenario } from '../../guidedPrototype/state';

export interface GuidedDescriptionReviewProps {
  scenario: GuidedScenario;
  resetVersion: number;
  onConfirmIdentity: () => void;
  onLeaveUnidentified: () => void;
  onSaveEdit: (text: string) => string | undefined;
  onReject: () => void;
  onApply: () => void;
  onUndo: () => void;
}

const identityLabel = (identity: GuidedIdentity): string => {
  if (identity.status === 'confirmed') {
    return `${identity.name} confirmed from the sample record.`;
  }
  if (identity.status === 'unidentified') {
    return 'Identity left unidentified.';
  }
  return 'Identity has not been confirmed.';
};

const candidateStatusLabel = (status: GuidedCandidateStatus): string => {
  if (status === 'edited') {
    return 'Edited by you';
  }
  if (status === 'rejected') {
    return 'Rejected; the applied text is unchanged';
  }
  return 'Ready for your review';
};

export const GuidedDescriptionReview = ({
  scenario,
  resetVersion,
  onConfirmIdentity,
  onLeaveUnidentified,
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
  const identityChangeReasonId = 'guided-identity-change-reason';
  const identityConfirmed = scenario.identity.status === 'confirmed';
  const identityUnidentified = scenario.identity.status === 'unidentified';

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
          <p className="acx-guided-review__eyebrow">Identity-informed description</p>
          <h2 id="acx-guided-review-title">Review before anything changes</h2>
        </div>
        <span className={`acx-guided-review__status acx-guided-review__status--${scenario.candidate.status}`}>
          {candidateStatusLabel(scenario.candidate.status)}
        </span>
      </header>

      <div className="acx-guided-review__context-grid">
        <div className="acx-guided-review__context-card">
          <h3 id="guided-visual-description-title">Visual description</h3>
          <ul>
            {scenario.visualFacts.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
          <p>
            Generic draft from visual facts: <span data-generic-draft>{scenario.genericDraft}</span>
          </p>
          <p>Current applied alt text: {scenario.appliedText}</p>
        </div>
        <div className="acx-guided-review__context-card">
          <h3 id="guided-page-context-title">Page context</h3>
          <p>
            <strong>{scenario.pageContext.title}</strong>
          </p>
          <p>{scenario.pageContext.summary}</p>
        </div>
        <div
          id="guided-section-identity"
          className="acx-guided-review__context-card"
          aria-labelledby="guided-identity-evidence-title"
          tabIndex={-1}
        >
          <h3 id="guided-identity-evidence-title">Identity evidence</h3>
          <p>{identityLabel(scenario.identity)}</p>
          <p>{scenario.sourceRecord.note}</p>
          <p id={identityChangeReasonId} className="acx-guided-review__identity-change-note">
            Changing the identity decision selects a different saved candidate description. Save or discard an unsaved
            edit first.
          </p>
          <div className="acx-guided-review__identity-actions">
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={onConfirmIdentity}
              disabled={hasUnsavedEdit || identityConfirmed}
              aria-describedby={
                hasUnsavedEdit ? unsavedEditReasonId : identityConfirmed ? identityChangeReasonId : undefined
              }
            >
              Confirm {scenario.sourceRecord.name}
            </button>
            <button
              type="button"
              className="acx-button acx-button--tertiary"
              onClick={onLeaveUnidentified}
              disabled={hasUnsavedEdit || identityUnidentified}
              aria-describedby={
                hasUnsavedEdit ? unsavedEditReasonId : identityUnidentified ? identityChangeReasonId : undefined
              }
            >
              Keep the person unidentified
            </button>
          </div>
        </div>
      </div>

      <section
        id="guided-section-review"
        className="acx-guided-review__comparison"
        aria-label="Review the description"
        data-testid="guided-candidate"
        tabIndex={-1}
      >
        <p className="acx-guided-review__explanation">
          {scenario.identity.status === 'confirmed'
            ? 'Confirmed identity changes the name in the candidate; the visual facts and page context stay visible.'
            : 'No confirmed name supplied; the visual description remains unchanged.'}
        </p>
        <div>
          <h3>Before</h3>
          <p>{scenario.genericDraft}</p>
        </div>
        <div>
          <h3>Proposed draft</h3>
          <p className="acx-guided-review__origin">Draft origin: {GUIDED_SCENARIO_ORIGIN_LABELS[scenario.origin]}</p>
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
          {scenario.candidate.status === 'rejected' && !hasUnsavedEdit ? (
            <p className="acx-guided-review__rejected-notice">
              This draft is rejected, so Apply is unavailable. Edit and save the description, or change the identity
              decision, to get a fresh draft to review.
            </p>
          ) : null}
          {hasUnsavedEdit ? (
            <p id={unsavedEditReasonId} className="acx-guided-review__unsaved-notice">
              Unsaved edit. Save this description before applying, or discard it to restore the saved candidate.
            </p>
          ) : null}
          <div className="acx-guided-review__actions">
            <button type="button" className="acx-button acx-button--secondary" onClick={handleSaveEdit}>
              Save description edit
            </button>
            {hasUnsavedEdit ? (
              <button type="button" className="acx-button acx-button--tertiary" onClick={handleDiscardEdit}>
                Discard unsaved edit
              </button>
            ) : null}
            <button
              type="button"
              className="acx-button acx-button--tertiary"
              onClick={onReject}
              disabled={scenario.candidate.status === 'rejected'}
            >
              Reject draft
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
          <h3>Explicit apply</h3>
          <p>
            The practice copy currently says <strong data-applied-text>{scenario.appliedText}</strong>. Applying writes
            the saved proposed draft to this practice scenario only.
          </p>
          {hasUnsavedEdit ? (
            <p className="acx-guided-review__apply-reason" id="guided-apply-reason">
              Apply is unavailable while your draft has unsaved edits. Save or discard the edit first.
            </p>
          ) : null}
        </div>
        <div className="acx-guided-review__actions">
          <button
            type="button"
            className="acx-button acx-button--primary"
            onClick={onApply}
            disabled={scenario.candidate.status === 'rejected' || hasUnsavedEdit}
            aria-describedby={hasUnsavedEdit ? 'guided-apply-reason' : undefined}
          >
            Apply to practice copy
          </button>
          {appliedEvent ? (
            <button type="button" className="acx-button acx-button--tertiary" onClick={onUndo}>
              Undo practice apply
            </button>
          ) : null}
        </div>
      </section>
    </section>
  );
};

GuidedDescriptionReview.displayName = 'GuidedDescriptionReview';

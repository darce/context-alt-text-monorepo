import React, { useEffect, useState } from 'react';

import type {
  GuidedCandidateStatus,
  GuidedHistoryEvent,
  GuidedIdentity,
  GuidedScenario,
} from '../../guidedPrototype/state';

export interface GuidedDescriptionReviewProps {
  scenario: GuidedScenario;
  onConfirmIdentity: () => void;
  onLeaveUnidentified: () => void;
  onSaveEdit: (text: string) => void;
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

const lastApplication = (history: GuidedHistoryEvent[]): GuidedHistoryEvent | undefined =>
  [...history].reverse().find((event) => event.kind === 'applied');

export const GuidedDescriptionReview = ({
  scenario,
  onConfirmIdentity,
  onLeaveUnidentified,
  onSaveEdit,
  onReject,
  onApply,
  onUndo,
}: GuidedDescriptionReviewProps): React.JSX.Element => {
  const [editValue, setEditValue] = useState(scenario.candidate.text);

  useEffect(() => {
    setEditValue(scenario.candidate.text);
  }, [scenario.candidate.text]);

  const appliedEvent = lastApplication(scenario.history);

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
          <h3>Visual description</h3>
          <ul>
            {scenario.visualFacts.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
          <p>Current applied alt text: {scenario.appliedText}</p>
        </div>
        <div className="acx-guided-review__context-card">
          <h3>Page context</h3>
          <p>
            <strong>{scenario.pageContext.title}</strong>
          </p>
          <p>{scenario.pageContext.summary}</p>
        </div>
        <div className="acx-guided-review__context-card">
          <h3>Identity evidence</h3>
          <p>{identityLabel(scenario.identity)}</p>
          <p>{scenario.sourceRecord.note}</p>
          <div className="acx-guided-review__identity-actions">
            <button type="button" className="acx-button acx-button--secondary" onClick={onConfirmIdentity}>
              Confirm {scenario.sourceRecord.name}
            </button>
            <button type="button" className="acx-button acx-button--tertiary" onClick={onLeaveUnidentified}>
              Keep the person unidentified
            </button>
          </div>
        </div>
      </div>

      <div className="acx-guided-review__comparison" data-testid="guided-candidate">
        <div>
          <h3>Before</h3>
          <p>{scenario.appliedText}</p>
        </div>
        <div>
          <h3>Proposed draft</h3>
          <label htmlFor="guided-description-draft">Description draft</label>
          <textarea
            id="guided-description-draft"
            aria-label="Description draft"
            value={editValue}
            rows={4}
            onChange={(event) => setEditValue(event.target.value)}
          />
          <div className="acx-guided-review__actions">
            <button type="button" className="acx-button acx-button--secondary" onClick={() => onSaveEdit(editValue)}>
              Save description edit
            </button>
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
      </div>

      <div className="acx-guided-review__apply" aria-live="polite">
        <div>
          <h3>Explicit apply</h3>
          <p>
            The practice copy currently says <strong data-applied-text>{scenario.appliedText}</strong>. Applying writes
            the proposed draft to this saved scenario only.
          </p>
        </div>
        <div className="acx-guided-review__actions">
          <button
            type="button"
            className="acx-button acx-button--primary"
            onClick={onApply}
            disabled={scenario.candidate.status === 'rejected'}
          >
            Apply to practice copy
          </button>
          {appliedEvent ? (
            <button type="button" className="acx-button acx-button--tertiary" onClick={onUndo}>
              Undo practice apply
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
};

GuidedDescriptionReview.displayName = 'GuidedDescriptionReview';

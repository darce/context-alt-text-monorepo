import React, { useEffect, useRef, useState } from 'react';

import { guidedCopy } from '../../guidedPrototype/copy';
import {
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  canApply,
  canPreview,
  canRestoreRevision,
  canUndo,
  type GuidedDemoState,
  type GuidedRestoreMode,
  type GuidedScenario,
} from '../../guidedPrototype/state';

export interface GuidedDescriptionReviewActions {
  onEdit: (text: string) => void;
  onPreview: (text: string) => void;
  onKeep: () => void;
  onRetryFixture: () => void;
  onRestore: (revisionId: string, mode: GuidedRestoreMode) => void;
  onApply: (text: string) => void;
  onUndo: () => void;
}

export interface GuidedDescriptionReviewProps {
  scenario: GuidedScenario;
  state: GuidedDemoState;
  actions: GuidedDescriptionReviewActions;
}

const originLabel = (state: GuidedDemoState): string => {
  switch (state.draftOrigin) {
    case GUIDED_DRAFT_ORIGIN.VISITOR_EDIT:
      return guidedCopy('draft.origin_edited');
    case GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE:
      return guidedCopy('draft.origin_saved');
    case GUIDED_DRAFT_ORIGIN.NONE:
      return '';
    default: {
      const exhaustive: never = state.draftOrigin;
      return exhaustive;
    }
  }
};

const applyReason = (state: GuidedDemoState, localText: string): string | null => {
  if (state.draftStatus === GUIDED_DRAFT_STATUS.BLOCKED) {
    return guidedCopy('draft.blocked');
  }
  if (state.draftStatus === GUIDED_DRAFT_STATUS.FIXTURE_MISSING) {
    return guidedCopy('draft.fixture_missing');
  }
  if (localText.trim() === '') {
    return guidedCopy('draft.empty_error');
  }
  if (localText !== (state.draftText ?? '')) {
    return guidedCopy('apply.stale');
  }
  if (state.previewedVersion !== state.draftVersion) {
    return guidedCopy('apply.stale');
  }
  if (state.draftText === state.appliedAltText) {
    return guidedCopy('apply.no_change');
  }
  return null;
};

export const GuidedDescriptionReview = ({
  scenario,
  state,
  actions,
}: GuidedDescriptionReviewProps): React.JSX.Element => {
  const [editValue, setEditValue] = useState(state.draftText ?? '');
  const [emptyError, setEmptyError] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setEditValue(state.draftText ?? '');
    setEmptyError(false);
  }, [state.draftText, state.draftVersion]);

  const ready = state.draftStatus === GUIDED_DRAFT_STATUS.READY;
  const missing = state.draftStatus === GUIDED_DRAFT_STATUS.FIXTURE_MISSING;
  const blocked = state.draftStatus === GUIDED_DRAFT_STATUS.BLOCKED;
  const localMatches = editValue === (state.draftText ?? '');
  const previewEnabled = ready && editValue.trim().length > 0;
  const applyEnabled = canApply(state) && localMatches;
  const undoEnabled = canUndo(state);
  const reason = applyReason(state, editValue);
  const previewBlocked = !canPreview(state) && localMatches ? reason : null;

  const handlePreview = (): void => {
    if (editValue.trim() === '') {
      setEmptyError(true);
      editorRef.current?.focus();
      return;
    }
    setEmptyError(false);
    actions.onPreview(editValue);
  };

  return (
    <>
      <section
        id="guided-section-review"
        className="acx-guided-review"
        aria-labelledby="acx-guided-review-title"
        data-testid="guided-candidate"
        tabIndex={-1}
      >
        <header className="acx-guided-review__header">
          <h2 id="acx-guided-review-title">{guidedCopy('step.draft')}</h2>
          <p>{guidedCopy('draft.intro')}</p>
        </header>

        {blocked ? <p>{guidedCopy('draft.blocked')}</p> : null}
        {missing ? (
          <div>
            <p>{guidedCopy('draft.fixture_missing')}</p>
            <button type="button" className="acx-button acx-button--secondary" onClick={actions.onRetryFixture}>
              {guidedCopy('draft.fixture_retry')}
            </button>
          </div>
        ) : null}

        {ready ? (
          <div className="acx-guided-review__comparison">
            <p className="acx-guided-review__origin">{originLabel(state)}</p>
            <label htmlFor="guided-description-draft">{guidedCopy('draft.label')}</label>
            <textarea
              ref={editorRef}
              id="guided-description-draft"
              aria-invalid={emptyError ? 'true' : undefined}
              aria-describedby={emptyError ? 'guided-description-draft-error' : undefined}
              value={editValue}
              rows={4}
              onChange={(event) => {
                setEditValue(event.target.value);
                setEmptyError(false);
              }}
            />
            {emptyError ? (
              <p id="guided-description-draft-error" className="acx-guided-review__field-error" role="alert">
                {guidedCopy('draft.empty_error')}
              </p>
            ) : null}
            <p>{guidedCopy('draft.effect')}</p>
            <div className="acx-guided-review__actions">
              <button
                type="button"
                className="acx-button acx-button--primary"
                onClick={handlePreview}
                disabled={!previewEnabled}
                aria-describedby={previewBlocked ? 'guided-preview-reason' : undefined}
              >
                {guidedCopy('draft.next')}
              </button>
              <button type="button" className="acx-button acx-button--tertiary" onClick={actions.onKeep}>
                {guidedCopy('draft.keep')}
              </button>
            </div>
            {previewBlocked ? (
              <p id="guided-preview-reason" className="acx-guided-review__apply-reason">
                {previewBlocked}
              </p>
            ) : null}
          </div>
        ) : (
          <div className="acx-guided-review__actions">
            <button type="button" className="acx-button acx-button--tertiary" onClick={actions.onKeep}>
              {guidedCopy('draft.keep')}
            </button>
          </div>
        )}

        {state.draftHistory.length > 0 ? (
          <details className="acx-guided-review__history">
            <summary>{guidedCopy('draft.history')}</summary>
            <p>{guidedCopy('draft.history_note')}</p>
            <ul>
              {state.draftHistory.map((revision) => {
                const matching = canRestoreRevision(state, revision.revisionId);
                return (
                  <li key={revision.revisionId}>
                    <p>{revision.text}</p>
                    {matching ? (
                      <button
                        type="button"
                        className="acx-button acx-button--tertiary"
                        onClick={() => actions.onRestore(revision.revisionId, 'full')}
                      >
                        {guidedCopy('draft.restore_revision')}
                      </button>
                    ) : (
                      <>
                        <p>{guidedCopy('draft.restore_guard')}</p>
                        <button
                          type="button"
                          className="acx-button acx-button--tertiary"
                          onClick={() => actions.onRestore(revision.revisionId, 'copy_only')}
                        >
                          {guidedCopy('draft.copy_revision')}
                        </button>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          </details>
        ) : null}
      </section>

      <section
        id="guided-section-apply"
        className="acx-guided-review acx-guided-review__apply"
        aria-labelledby="acx-guided-apply-title"
        tabIndex={-1}
      >
        <h2 id="acx-guided-apply-title">{guidedCopy('step.apply')}</h2>
        <p>{guidedCopy('apply.intro')}</p>
        <div className="acx-guided-review__preview-grid">
          <div>
            <h3>{guidedCopy('apply.before')}</h3>
            <p data-applied-text>{state.appliedAltText}</p>
          </div>
          <div>
            <h3>{guidedCopy('apply.after')}</h3>
            <p>{localMatches ? (state.draftText ?? '') : editValue}</p>
          </div>
        </div>
        <figure className="acx-guided-review__demo-preview">
          <figcaption>{guidedCopy('apply.preview_title')}</figcaption>
          <img
            data-testid="demo-applied-image"
            src={`${scenario.pressPhoto.src}#demo-applied-preview`}
            alt={state.appliedAltText}
          />
        </figure>
        <div className="acx-guided-review__actions">
          <button
            type="button"
            className="acx-button acx-button--primary"
            data-testid="demo-apply"
            onClick={() => actions.onApply(editValue)}
            disabled={!applyEnabled}
            aria-describedby={!applyEnabled && reason ? 'guided-apply-reason' : undefined}
          >
            {guidedCopy('apply.submit')}
          </button>
          <button
            type="button"
            className="acx-button acx-button--tertiary"
            data-testid="demo-undo"
            onClick={actions.onUndo}
            disabled={!undoEnabled}
            aria-describedby={!undoEnabled ? 'guided-undo-reason' : undefined}
          >
            {guidedCopy('apply.undo')}
          </button>
        </div>
        {!applyEnabled && reason ? (
          <p id="guided-apply-reason" className="acx-guided-review__apply-reason">
            {reason}
          </p>
        ) : null}
        {!undoEnabled ? (
          <p id="guided-undo-reason" className="acx-guided-review__apply-reason">
            {guidedCopy('apply.undo_unavailable')}
          </p>
        ) : null}
      </section>
    </>
  );
};

GuidedDescriptionReview.displayName = 'GuidedDescriptionReview';

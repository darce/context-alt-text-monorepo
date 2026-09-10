import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

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
  onDraftInput: (text: string) => void;
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
  recordedOriginLabel?: string;
}

const originLabel = (state: GuidedDemoState, recordedOriginLabel?: string): string => {
  switch (state.draftOrigin) {
    case GUIDED_DRAFT_ORIGIN.VISITOR_EDIT:
      return guidedCopy('draft.origin_edited');
    case GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE:
      return recordedOriginLabel ?? guidedCopy('draft.origin_saved');
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
  recordedOriginLabel,
}: GuidedDescriptionReviewProps): React.JSX.Element => {
  const [editValue, setEditValue] = useState(state.draftText ?? '');
  const [emptyError, setEmptyError] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const comparisonRef = useRef<HTMLDivElement>(null);
  const manuallyResizedHeightRef = useRef<number | null>(null);
  const editorPointerActiveRef = useRef(false);
  const previousDraftTextRef = useRef(state.draftText);
  const onDraftInputRef = useRef(actions.onDraftInput);
  onDraftInputRef.current = actions.onDraftInput;
  const ready = state.draftStatus === GUIDED_DRAFT_STATUS.READY;
  const missing = state.draftStatus === GUIDED_DRAFT_STATUS.FIXTURE_MISSING;
  const blocked = state.draftStatus === GUIDED_DRAFT_STATUS.BLOCKED;

  const resizeEditor = useCallback((): void => {
    const editor = editorRef.current;
    if (editor === null) {
      return;
    }

    const previousHeight = editor.style.height;
    editor.style.height = 'auto';
    const contentHeight = editor.scrollHeight;
    const minimumHeight = editor.offsetHeight;
    const autoHeight = Math.max(contentHeight, minimumHeight);
    const manualHeight = manuallyResizedHeightRef.current ?? 0;
    const nextHeight = Math.max(autoHeight, manualHeight);

    // jsdom does not lay out a textarea, so both measurements can be zero in
    // tests. Leave the browser's rows/min-height sizing intact in that case.
    if (nextHeight > 0) {
      editor.style.height = `${nextHeight}px`;
    } else {
      editor.style.height = previousHeight;
    }
  }, []);

  const rememberManualEditorSize = (): void => {
    const editor = editorRef.current;
    if (editor === null) {
      return;
    }
    const measuredHeight = editor.getBoundingClientRect().height || editor.offsetHeight;
    if (measuredHeight > 0) {
      manuallyResizedHeightRef.current = measuredHeight;
    }
    editorPointerActiveRef.current = false;
  };

  const beginEditorPointerInteraction = (): void => {
    editorPointerActiveRef.current = true;
  };

  useEffect(() => {
    const text = state.draftText ?? '';
    setEditValue(text);
    setEmptyError(false);
    onDraftInputRef.current(text);
  }, [state.draftText, state.draftVersion]);

  useLayoutEffect(() => {
    if (previousDraftTextRef.current !== state.draftText) {
      previousDraftTextRef.current = state.draftText;
      manuallyResizedHeightRef.current = null;
    }
    resizeEditor();
  }, [editValue, ready, resizeEditor, state.draftText, state.draftVersion]);

  useEffect(() => {
    if (!ready) {
      return undefined;
    }

    const comparison = comparisonRef.current;
    if (comparison === null) {
      return undefined;
    }

    const handleResize = (): void => {
      if (!editorPointerActiveRef.current) {
        resizeEditor();
      }
    };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(handleResize);
    observer?.observe(comparison);
    window.addEventListener('resize', handleResize);

    const fontSet = document.fonts;
    fontSet?.addEventListener('loadingdone', handleResize);
    fontSet?.addEventListener('loadingerror', handleResize);

    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', handleResize);
      fontSet?.removeEventListener('loadingdone', handleResize);
      fontSet?.removeEventListener('loadingerror', handleResize);
    };
  }, [ready, resizeEditor]);

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
          <div ref={comparisonRef} className="acx-guided-review__comparison">
            <p className="acx-guided-review__origin">{originLabel(state, recordedOriginLabel)}</p>
            <label htmlFor="guided-description-draft">{guidedCopy('draft.label')}</label>
            <textarea
              ref={editorRef}
              id="guided-description-draft"
              aria-invalid={emptyError ? 'true' : undefined}
              aria-describedby={emptyError ? 'guided-description-draft-error' : undefined}
              value={editValue}
              rows={8}
              onInput={resizeEditor}
              onPointerDown={beginEditorPointerInteraction}
              onPointerUp={rememberManualEditorSize}
              onPointerCancel={() => {
                editorPointerActiveRef.current = false;
              }}
              onMouseDown={beginEditorPointerInteraction}
              onMouseUp={rememberManualEditorSize}
              onTouchStart={beginEditorPointerInteraction}
              onTouchEnd={rememberManualEditorSize}
              onTouchCancel={() => {
                editorPointerActiveRef.current = false;
              }}
              onChange={(event) => {
                const text = event.target.value;
                setEditValue(text);
                setEmptyError(false);
                onDraftInputRef.current(text);
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

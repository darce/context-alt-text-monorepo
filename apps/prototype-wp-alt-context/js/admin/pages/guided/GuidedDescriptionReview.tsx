import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  canApply,
  canApplyImageDraftPublic,
  canPreview,
  canRestoreRevision,
  canUndo,
  type GuidedDemoState,
  type GuidedImageKey,
  type GuidedRestoreMode,
  type GuidedScenario,
} from '../../guidedPrototype/state';
import {
  guidedReviewCanApply,
  guidedReviewCanPreview,
  guidedReviewCanRestore,
  guidedReviewCanUndo,
  guidedReviewDraftFor,
  guidedReviewLegacyState,
  guidedReviewNamesDecided,
  GUIDED_REVIEW_TRIBECA_KEY,
  hasGuidedImageDrafts,
  type GuidedImageAction,
  type GuidedImageDraft,
  type GuidedRestoreAction,
  type GuidedReviewState,
  type GuidedTextAction,
} from '../../guidedPrototype/reviewDrafts';

export interface GuidedDescriptionReviewActions {
  onEdit: (text: string) => void;
  onDraftInput: (text: string) => void;
  onPreview: (text: string) => void;
  onKeep: () => void;
  onRetryFixture: () => void;
  onRestore: (revisionId: string, mode: GuidedRestoreMode) => void;
  onApply: (text: string) => void;
  onUndo: () => void;
  onEditForImage?: (imageKey: GuidedImageKey, text: string) => void;
  onDraftInputForImage?: (imageKey: GuidedImageKey, text: string) => void;
  onPreviewForImage?: (imageKey: GuidedImageKey, text: string) => void;
  onKeepForImage?: (imageKey: GuidedImageKey) => void;
  onRetryFixtureForImage?: (imageKey: GuidedImageKey) => void;
  onRestoreForImage?: (imageKey: GuidedImageKey, revisionId: string, mode: GuidedRestoreMode) => void;
  onApplyForImage?: (imageKey: GuidedImageKey, text: string) => void;
  onUndoForImage?: (imageKey: GuidedImageKey) => void;
}

export interface GuidedDescriptionReviewProps {
  scenario: GuidedScenario;
  state: GuidedReviewState;
  actions: GuidedDescriptionReviewActions;
  recordedOriginLabel?: string;
  scope?: 'public' | 'admin';
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

const imageOriginLabel = (draft: GuidedImageDraft, recordedOriginLabel?: string): string => {
  switch (draft.draftOrigin) {
    case GUIDED_DRAFT_ORIGIN.VISITOR_EDIT:
      return guidedCopy('draft.origin_edited');
    case GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE:
      return recordedOriginLabel ?? guidedCopy('draft.origin_saved');
    case GUIDED_DRAFT_ORIGIN.NONE:
      return '';
    default: {
      const exhaustive: never = draft.draftOrigin;
      return exhaustive;
    }
  }
};

const imageApplyReason = (state: GuidedReviewState, draft: GuidedImageDraft, localText: string): string | null => {
  if (draft.draftStatus === GUIDED_DRAFT_STATUS.BLOCKED) {
    return guidedCopy('draft.blocked');
  }
  if (draft.draftStatus === GUIDED_DRAFT_STATUS.FIXTURE_MISSING) {
    return guidedCopy('draft.fixture_missing');
  }
  if (localText.trim() === '') {
    return guidedCopy('draft.empty_error');
  }
  if (localText !== (draft.draftText ?? '')) {
    return guidedCopy('apply.stale');
  }
  if (draft.previewedVersion !== draft.draftVersion) {
    return guidedCopy('apply.stale');
  }
  if (draft.draftText === draft.appliedAltText) {
    return guidedCopy('apply.no_change');
  }
  if (!guidedReviewNamesDecided(state)) {
    return guidedCopy('draft.blocked');
  }
  return null;
};

const imagePublicApplyReason = (state: GuidedReviewState, draft: GuidedImageDraft, localText: string): string | null => {
  if (draft.draftStatus !== GUIDED_DRAFT_STATUS.READY || draft.draftText === null) {
    return guidedCopy('error.no_recorded_draft.public');
  }
  if (localText.trim() === '') {
    return guidedCopy('error.empty_draft.public');
  }
  if (localText === draft.appliedAltText) {
    return guidedCopy('error.unchanged_draft.public');
  }
  if (!guidedReviewNamesDecided(state) || state.pendingChoiceChange !== null) {
    return guidedCopy('error.no_recorded_draft.public');
  }
  return null;
};

const callTextAction = (action: GuidedTextAction, imageKey: GuidedImageKey, text: string, perImage: boolean): void => {
  if (perImage) {
    action(imageKey, text);
    return;
  }
  (action as (value: string) => void)(text);
};

const callImageAction = (action: GuidedImageAction, imageKey: GuidedImageKey, perImage: boolean): void => {
  if (perImage) {
    action(imageKey);
    return;
  }
  (action as () => void)();
};

const callRestoreAction = (
  action: GuidedRestoreAction,
  imageKey: GuidedImageKey,
  revisionId: string,
  mode: GuidedRestoreMode,
  perImage: boolean,
): void => {
  if (perImage) {
    (action as (key: GuidedImageKey, id: string, restoreMode: GuidedRestoreMode) => void)(imageKey, revisionId, mode);
    return;
  }
  (action as (id: string, restoreMode: GuidedRestoreMode) => void)(revisionId, mode);
};

const callTextImageAction = (
  imageAction: ((imageKey: GuidedImageKey, text: string) => void) | undefined,
  action: GuidedTextAction,
  imageKey: GuidedImageKey,
  text: string,
  perImage: boolean,
): void => {
  if (perImage && imageAction !== undefined) {
    imageAction(imageKey, text);
    return;
  }
  callTextAction(action, imageKey, text, perImage);
};

const callImageOnlyAction = (
  imageAction: ((imageKey: GuidedImageKey) => void) | undefined,
  action: GuidedImageAction,
  imageKey: GuidedImageKey,
  perImage: boolean,
): void => {
  if (perImage && imageAction !== undefined) {
    imageAction(imageKey);
    return;
  }
  callImageAction(action, imageKey, perImage);
};

const callImageRestoreAction = (
  imageAction: ((imageKey: GuidedImageKey, revisionId: string, mode: GuidedRestoreMode) => void) | undefined,
  action: GuidedRestoreAction,
  imageKey: GuidedImageKey,
  revisionId: string,
  mode: GuidedRestoreMode,
  perImage: boolean,
): void => {
  if (perImage && imageAction !== undefined) {
    imageAction(imageKey, revisionId, mode);
    return;
  }
  callRestoreAction(action, imageKey, revisionId, mode, perImage);
};

const readPixelValue = (value: string): number => {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const readEditorHeight = (editor: HTMLTextAreaElement): number =>
  editor.getBoundingClientRect().height || editor.offsetHeight;

interface GuidedImageReviewCardProps {
  photo: GuidedScenario['pressPhotos'][number];
  state: GuidedReviewState;
  draft: GuidedImageDraft;
  actions: GuidedDescriptionReviewActions;
  recordedOriginLabel?: string;
  scope: 'public' | 'admin';
}

const GuidedImageReviewCard = ({
  photo,
  state,
  draft,
  actions,
  recordedOriginLabel,
  scope,
}: GuidedImageReviewCardProps): React.JSX.Element => {
  const [editValue, setEditValue] = useState(draft.draftText ?? '');
  const [emptyError, setEmptyError] = useState(false);
  const [publicStatus, setPublicStatus] = useState('');
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const comparisonRef = useRef<HTMLDivElement>(null);
  const manuallyResizedHeightRef = useRef<number | null>(null);
  const editorPointerActiveRef = useRef(false);
  const editorInteractionStartHeightRef = useRef<number | null>(null);
  const previousDraftTextRef = useRef(draft.draftText);

  const resizeEditor = useCallback((): void => {
    const editor = editorRef.current;
    if (editor === null) {
      return;
    }

    const previousHeight = editor.style.height;
    editor.style.height = 'auto';
    const contentHeight = editor.scrollHeight;
    const computedStyle = window.getComputedStyle(editor);
    const paddingHeight = readPixelValue(computedStyle.paddingTop) + readPixelValue(computedStyle.paddingBottom);
    const borderHeight = readPixelValue(computedStyle.borderTopWidth) + readPixelValue(computedStyle.borderBottomWidth);
    const autoHeight = Math.max(contentHeight + borderHeight, editor.offsetHeight);
    const manualHeight = manuallyResizedHeightRef.current ?? 0;
    const nextOuterHeight = Math.max(autoHeight, manualHeight);
    const isBorderBox = (computedStyle.boxSizing || 'border-box') === 'border-box';
    const nextCssHeight = isBorderBox ? nextOuterHeight : Math.max(nextOuterHeight - paddingHeight - borderHeight, 0);

    if (nextOuterHeight > 0) {
      editor.style.height = `${nextCssHeight}px`;
    } else {
      editor.style.height = previousHeight;
    }
  }, []);

  const cancelEditorPointerInteraction = useCallback((): void => {
    editorPointerActiveRef.current = false;
    editorInteractionStartHeightRef.current = null;
  }, []);

  const rememberManualEditorSize = useCallback((): void => {
    if (!editorPointerActiveRef.current) {
      return;
    }
    const editor = editorRef.current;
    const interactionStartHeight = editorInteractionStartHeightRef.current;
    editorPointerActiveRef.current = false;
    editorInteractionStartHeightRef.current = null;
    if (editor === null || interactionStartHeight === null) {
      return;
    }

    const measuredHeight = readEditorHeight(editor);
    if (measuredHeight > 0 && measuredHeight !== interactionStartHeight) {
      manuallyResizedHeightRef.current = measuredHeight;
    }
  }, []);

  const beginEditorPointerInteraction = useCallback((): void => {
    if (editorPointerActiveRef.current) {
      return;
    }
    editorPointerActiveRef.current = true;
    const editor = editorRef.current;
    editorInteractionStartHeightRef.current = editor === null ? null : readEditorHeight(editor);
  }, []);

  useEffect(() => {
    setEditValue(draft.draftText ?? '');
    setEmptyError(false);
  }, [draft.draftText, draft.draftVersion]);

  useLayoutEffect(() => {
    if (previousDraftTextRef.current !== draft.draftText) {
      previousDraftTextRef.current = draft.draftText;
      manuallyResizedHeightRef.current = null;
    }
    resizeEditor();
  }, [draft.draftText, draft.draftVersion, editValue, resizeEditor]);

  useEffect(() => {
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
  }, [resizeEditor]);

  useEffect(() => {
    const releaseEvents = ['pointerup', 'mouseup', 'touchend'] as const;
    const cancelEvents = ['pointercancel', 'touchcancel', 'cancel', 'blur'] as const;
    const handleRelease = (): void => {
      rememberManualEditorSize();
    };
    const handleCancel = (): void => {
      cancelEditorPointerInteraction();
    };
    const targets: (Window | Document)[] = [window, document];

    targets.forEach((target) => {
      releaseEvents.forEach((eventName) => target.addEventListener(eventName, handleRelease, true));
      cancelEvents.forEach((eventName) => target.addEventListener(eventName, handleCancel, true));
    });

    return () => {
      targets.forEach((target) => {
        releaseEvents.forEach((eventName) => target.removeEventListener(eventName, handleRelease, true));
        cancelEvents.forEach((eventName) => target.removeEventListener(eventName, handleCancel, true));
      });
      cancelEditorPointerInteraction();
    };
  }, [cancelEditorPointerInteraction, rememberManualEditorSize]);

  const localMatches = editValue === (draft.draftText ?? '');
  const previewEnabled = draft.draftStatus === GUIDED_DRAFT_STATUS.READY && editValue.trim().length > 0;
  const publicApplyDraft: GuidedDemoState['drafts'][GuidedImageKey] = {
    ...draft,
    draftVersion: draft.draftVersion ?? 0,
    previewedVersion: draft.previewedVersion ?? null,
    draftText: editValue,
  };
  const applyEnabled =
    scope === 'public'
      ? draft.draftText !== null && canApplyImageDraftPublic(state as unknown as GuidedDemoState, publicApplyDraft)
      : guidedReviewCanApply(state, draft) && localMatches;
  const undoEnabled = guidedReviewCanUndo(draft);
  const reason =
    scope === 'public' ? imagePublicApplyReason(state, draft, editValue) : imageApplyReason(state, draft, editValue);
  const previewBlocked = scope === 'admin' && !guidedReviewCanPreview(state, draft) && localMatches ? reason : null;
  const editorId = `guided-description-draft-${photo.key}`;
  const errorId = `${editorId}-error`;
  const applyReasonId = `${editorId}-apply-reason`;
  const undoReasonId = `${editorId}-undo-reason`;

  const handlePreview = (): void => {
    if (editValue.trim() === '') {
      setEmptyError(true);
      editorRef.current?.focus();
      return;
    }
    setEmptyError(false);
    callTextImageAction(actions.onPreviewForImage, actions.onPreview, photo.key, editValue, true);
  };

  const handlePublicApply = (): void => {
    if (editValue.trim() === '') {
      setEmptyError(true);
      editorRef.current?.focus();
      return;
    }
    if (!applyEnabled) {
      return;
    }
    setEmptyError(false);
    callTextImageAction(actions.onApplyForImage, actions.onApply, photo.key, editValue, true);
    setPublicStatus(guidedCopy('outcome.applied_image.public'));
  };

  const handlePublicUndo = (): void => {
    if (!undoEnabled) {
      return;
    }
    callImageOnlyAction(actions.onUndoForImage, actions.onUndo, photo.key, true);
    setPublicStatus(guidedCopy('outcome.undone_image.public'));
  };

  return (
    <article
      className="acx-guided-review__image-card"
      data-testid={`guided-description-review-${photo.key}`}
      data-image-key={photo.key}
      aria-labelledby={`${editorId}-title`}
    >
      <h3 id={`${editorId}-title`}>{photo.event}</h3>
      <p role="status" data-testid={`guided-image-status-${photo.key}`}>
        {publicStatus}
      </p>
      {draft.draftStatus === GUIDED_DRAFT_STATUS.BLOCKED ? <p>{guidedCopy('draft.blocked')}</p> : null}
      {draft.draftStatus === GUIDED_DRAFT_STATUS.FIXTURE_MISSING ? (
        <div>
          {scope === 'admin' ? <p>{guidedCopy('draft.fixture_missing')}</p> : null}
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={() => callImageOnlyAction(actions.onRetryFixtureForImage, actions.onRetryFixture, photo.key, true)}
          >
            {guidedCopy('draft.fixture_retry')}
          </button>
        </div>
      ) : null}

      {draft.draftStatus === GUIDED_DRAFT_STATUS.READY ? (
        scope === 'public' ? (
          <div
            ref={comparisonRef}
            className="acx-guided-review__comparison acx-guided-review__editor-layout"
            data-testid={`guided-editor-layout-${photo.key}`}
          >
            <figure className="acx-guided-review__demo-preview">
              <figcaption>{guidedCopy('apply.preview_title')}</figcaption>
              <img
                data-testid={`demo-applied-image-${photo.key}`}
                src={`${photo.src}#demo-applied-preview-${photo.key}`}
                alt={draft.appliedAltText}
              />
            </figure>
            <div data-testid={`guided-editor-column-${photo.key}`}>
              <p className="acx-guided-review__origin">{imageOriginLabel(draft, recordedOriginLabel)}</p>
              <div data-testid={`guided-current-alt-${photo.key}`}>
                <h4>{guidedCopy('draft.current_alt_label.public')}</h4>
                <p data-applied-text>{draft.appliedAltText}</p>
              </div>
              <div data-testid={`guided-draft-field-${photo.key}`}>
                <label htmlFor={editorId}>{guidedCopy('draft.field_label.public')}</label>
                <textarea
                  ref={editorRef}
                  id={editorId}
                  aria-invalid={emptyError ? 'true' : undefined}
                  aria-describedby={emptyError ? errorId : undefined}
                  value={editValue}
                  rows={8}
                  onInput={resizeEditor}
                  onPointerDown={beginEditorPointerInteraction}
                  onPointerUp={rememberManualEditorSize}
                  onPointerCancel={cancelEditorPointerInteraction}
                  onMouseDown={beginEditorPointerInteraction}
                  onMouseUp={rememberManualEditorSize}
                  onTouchStart={beginEditorPointerInteraction}
                  onTouchEnd={rememberManualEditorSize}
                  onTouchCancel={cancelEditorPointerInteraction}
                  onChange={(event) => {
                    const text = event.target.value;
                    setEditValue(text);
                    setEmptyError(false);
                    callTextImageAction(actions.onDraftInputForImage, actions.onDraftInput, photo.key, text, true);
                  }}
                />
                {emptyError ? (
                  <p id={errorId} className="acx-guided-review__field-error" role="alert">
                    {guidedCopy('error.empty_draft.public')}
                  </p>
                ) : null}
              </div>
              <p>{guidedCopy('draft.apply_scope.public')}</p>
              <div className="acx-guided-review__apply" data-testid={`guided-apply-${photo.key}`}>
                <button
                  type="button"
                  className="acx-button acx-button--primary"
                  data-testid={`demo-apply-${photo.key}`}
                  onClick={handlePublicApply}
                  disabled={!applyEnabled}
                  aria-describedby={!applyEnabled && reason ? applyReasonId : undefined}
                >
                  {guidedCopy('apply.submit')}
                </button>
                <button
                  type="button"
                  className="acx-button acx-button--tertiary"
                  data-testid={`guided-keep-current-${photo.key}`}
                  onClick={() => callImageOnlyAction(actions.onKeepForImage, actions.onKeep, photo.key, true)}
                >
                  {guidedCopy('draft.keep')}
                </button>
                <button
                  type="button"
                  className="acx-button acx-button--tertiary"
                  data-testid={`demo-undo-${photo.key}`}
                  onClick={handlePublicUndo}
                  disabled={!undoEnabled}
                >
                  {guidedCopy('apply.undo')}
                </button>
                {!applyEnabled && reason ? (
                  <p id={applyReasonId} className="acx-guided-review__apply-reason">
                    {reason}
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        ) : (
          <>
            <div ref={comparisonRef} className="acx-guided-review__comparison">
              <div>
                <p className="acx-guided-review__origin">{imageOriginLabel(draft, recordedOriginLabel)}</p>
                <label htmlFor={editorId}>{guidedCopy('draft.label')}</label>
                <textarea
                  ref={editorRef}
                  id={editorId}
                  aria-invalid={emptyError ? 'true' : undefined}
                  aria-describedby={emptyError ? errorId : undefined}
                  value={editValue}
                  rows={8}
                  onInput={resizeEditor}
                  onPointerDown={beginEditorPointerInteraction}
                  onPointerUp={rememberManualEditorSize}
                  onPointerCancel={cancelEditorPointerInteraction}
                  onMouseDown={beginEditorPointerInteraction}
                  onMouseUp={rememberManualEditorSize}
                  onTouchStart={beginEditorPointerInteraction}
                  onTouchEnd={rememberManualEditorSize}
                  onTouchCancel={cancelEditorPointerInteraction}
                  onChange={(event) => {
                    const text = event.target.value;
                    setEditValue(text);
                    setEmptyError(false);
                    callTextImageAction(actions.onDraftInputForImage, actions.onDraftInput, photo.key, text, true);
                  }}
                />
                {emptyError ? (
                  <p id={errorId} className="acx-guided-review__field-error" role="alert">
                    {guidedCopy('draft.empty_error')}
                  </p>
                ) : null}
                <p>{guidedCopy('draft.effect')}</p>
                <div className="acx-guided-review__actions" aria-label={`${photo.event} draft actions`}>
                  <button
                    type="button"
                    className="acx-button acx-button--primary"
                    onClick={handlePreview}
                    disabled={!previewEnabled}
                    aria-describedby={previewBlocked ? `${editorId}-preview-reason` : undefined}
                  >
                    {guidedCopy('draft.next')}
                  </button>
                  <button
                    type="button"
                    className="acx-button acx-button--tertiary"
                    onClick={() => callImageOnlyAction(actions.onKeepForImage, actions.onKeep, photo.key, true)}
                  >
                    {guidedCopy('draft.keep')}
                  </button>
                </div>
                {previewBlocked ? (
                  <p id={`${editorId}-preview-reason`} className="acx-guided-review__apply-reason">
                    {previewBlocked}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="acx-guided-review__apply" data-testid={`guided-apply-${photo.key}`}>
              <div className="acx-guided-review__preview-grid">
                <div>
                  <h4>{guidedCopy('apply.before')}</h4>
                  <p data-applied-text>{draft.appliedAltText}</p>
                </div>
                <div>
                  <h4>{guidedCopy('apply.after')}</h4>
                  <p>{localMatches ? (draft.draftText ?? '') : editValue}</p>
                </div>
              </div>
              <figure className="acx-guided-review__demo-preview">
                <figcaption>{guidedCopy('apply.preview_title')}</figcaption>
                <img
                  data-testid={`demo-applied-image-${photo.key}`}
                  src={`${photo.src}#demo-applied-preview-${photo.key}`}
                  alt={draft.appliedAltText}
                />
              </figure>
              <div className="acx-guided-review__actions" aria-label={`${photo.event} apply actions`}>
                <button
                  type="button"
                  className="acx-button acx-button--primary"
                  data-testid={`demo-apply-${photo.key}`}
                  onClick={() =>
                    callTextImageAction(actions.onApplyForImage, actions.onApply, photo.key, editValue, true)
                  }
                  disabled={!applyEnabled}
                  aria-describedby={!applyEnabled && reason ? applyReasonId : undefined}
                >
                  {guidedCopy('apply.submit')}
                </button>
                <button
                  type="button"
                  className="acx-button acx-button--tertiary"
                  data-testid={`demo-undo-${photo.key}`}
                  onClick={() => callImageOnlyAction(actions.onUndoForImage, actions.onUndo, photo.key, true)}
                  disabled={!undoEnabled}
                  aria-describedby={!undoEnabled ? undoReasonId : undefined}
                >
                  {guidedCopy('apply.undo')}
                </button>
              </div>
              {!applyEnabled && reason ? (
                <p id={applyReasonId} className="acx-guided-review__apply-reason">
                  {reason}
                </p>
              ) : null}
              {!undoEnabled ? (
                <p id={undoReasonId} className="acx-guided-review__apply-reason">
                  {guidedCopy('apply.undo_unavailable')}
                </p>
              ) : null}
            </div>
          </>
        )
      ) : scope === 'public' ? (
        <div className="acx-guided-review__apply" data-testid={`guided-apply-${photo.key}`}>
          <button
            type="button"
            className="acx-button acx-button--primary"
            data-testid={`demo-apply-${photo.key}`}
            onClick={handlePublicApply}
            disabled={!applyEnabled}
            aria-describedby={reason ? applyReasonId : undefined}
          >
            {guidedCopy('apply.submit')}
          </button>
          <button
            type="button"
            className="acx-button acx-button--tertiary"
            data-testid={`guided-keep-current-${photo.key}`}
            onClick={() => callImageOnlyAction(actions.onKeepForImage, actions.onKeep, photo.key, true)}
          >
            {guidedCopy('draft.keep')}
          </button>
          <button
            type="button"
            className="acx-button acx-button--tertiary"
            data-testid={`demo-undo-${photo.key}`}
            onClick={handlePublicUndo}
            disabled={!undoEnabled}
          >
            {guidedCopy('apply.undo')}
          </button>
          {reason ? (
            <p id={applyReasonId} className="acx-guided-review__apply-reason">
              {reason}
            </p>
          ) : null}
        </div>
      ) : (
        <div className="acx-guided-review__actions">
          <button
            type="button"
            className="acx-button acx-button--tertiary"
            onClick={() => callImageOnlyAction(actions.onKeepForImage, actions.onKeep, photo.key, true)}
          >
            {guidedCopy('draft.keep')}
          </button>
        </div>
      )}

      {draft.draftHistory.length > 0 ? (
        <details className="acx-guided-review__history">
          <summary>{guidedCopy('draft.history')}</summary>
          <p>{guidedCopy('draft.history_note')}</p>
          <ul>
            {draft.draftHistory.map((revision) => {
              const matching = guidedReviewCanRestore(state, draft, revision.revisionId);
              return (
                <li key={revision.revisionId} data-image-key={photo.key}>
                  <p>{revision.text}</p>
                  {matching ? (
                    <button
                      type="button"
                      className="acx-button acx-button--tertiary"
                      onClick={() =>
                        callImageRestoreAction(
                          actions.onRestoreForImage,
                          actions.onRestore,
                          photo.key,
                          revision.revisionId,
                          'full',
                          true,
                        )
                      }
                    >
                      {guidedCopy('draft.restore_revision')}
                    </button>
                  ) : (
                    <>
                      <p>{guidedCopy('draft.restore_guard')}</p>
                      <button
                        type="button"
                        className="acx-button acx-button--tertiary"
                        onClick={() =>
                          callImageRestoreAction(
                            actions.onRestoreForImage,
                            actions.onRestore,
                            photo.key,
                            revision.revisionId,
                            'copy_only',
                            true,
                          )
                        }
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
    </article>
  );
};

export const GuidedDescriptionReview = ({
  scenario,
  state: reviewState,
  actions,
  recordedOriginLabel,
  scope = 'admin',
}: GuidedDescriptionReviewProps): React.JSX.Element => {
  const perImage = hasGuidedImageDrafts(reviewState);
  const state = guidedReviewLegacyState(reviewState);
  const [editValue, setEditValue] = useState(state.draftText ?? '');
  const [emptyError, setEmptyError] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const comparisonRef = useRef<HTMLDivElement>(null);
  const manuallyResizedHeightRef = useRef<number | null>(null);
  const editorPointerActiveRef = useRef(false);
  const editorInteractionStartHeightRef = useRef<number | null>(null);
  const previousDraftTextRef = useRef(state.draftText);
  const onDraftInputRef = useRef<(text: string) => void>(() => undefined);
  onDraftInputRef.current = (text: string): void => {
    callTextAction(actions.onDraftInput, GUIDED_REVIEW_TRIBECA_KEY, text, false);
  };
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
    const computedStyle = window.getComputedStyle(editor);
    const paddingHeight = readPixelValue(computedStyle.paddingTop) + readPixelValue(computedStyle.paddingBottom);
    const borderHeight = readPixelValue(computedStyle.borderTopWidth) + readPixelValue(computedStyle.borderBottomWidth);
    const autoHeight = Math.max(contentHeight + borderHeight, editor.offsetHeight);
    const manualHeight = manuallyResizedHeightRef.current ?? 0;
    const nextOuterHeight = Math.max(autoHeight, manualHeight);
    const isBorderBox = (computedStyle.boxSizing || 'border-box') === 'border-box';
    const nextCssHeight = isBorderBox ? nextOuterHeight : Math.max(nextOuterHeight - paddingHeight - borderHeight, 0);

    // jsdom does not lay out a textarea, so both measurements can be zero in
    // tests. Leave the browser's rows/min-height sizing intact in that case.
    if (nextOuterHeight > 0) {
      editor.style.height = `${nextCssHeight}px`;
    } else {
      editor.style.height = previousHeight;
    }
  }, []);

  const cancelEditorPointerInteraction = useCallback((): void => {
    editorPointerActiveRef.current = false;
    editorInteractionStartHeightRef.current = null;
  }, []);

  const rememberManualEditorSize = useCallback((): void => {
    if (!editorPointerActiveRef.current) {
      return;
    }
    const editor = editorRef.current;
    const interactionStartHeight = editorInteractionStartHeightRef.current;
    editorPointerActiveRef.current = false;
    editorInteractionStartHeightRef.current = null;
    if (editor === null || interactionStartHeight === null) {
      return;
    }

    const measuredHeight = readEditorHeight(editor);
    if (measuredHeight > 0 && measuredHeight !== interactionStartHeight) {
      manuallyResizedHeightRef.current = measuredHeight;
    }
  }, []);

  const beginEditorPointerInteraction = useCallback((): void => {
    if (editorPointerActiveRef.current) {
      return;
    }
    editorPointerActiveRef.current = true;
    const editor = editorRef.current;
    editorInteractionStartHeightRef.current = editor === null ? null : readEditorHeight(editor);
  }, []);

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

  useEffect(() => {
    if (!ready) {
      return undefined;
    }

    const releaseEvents = ['pointerup', 'mouseup', 'touchend'] as const;
    const cancelEvents = ['pointercancel', 'touchcancel', 'cancel', 'blur'] as const;
    const handleRelease = (): void => {
      rememberManualEditorSize();
    };
    const handleCancel = (): void => {
      cancelEditorPointerInteraction();
    };
    const targets: (Window | Document)[] = [window, document];

    targets.forEach((target) => {
      releaseEvents.forEach((eventName) => target.addEventListener(eventName, handleRelease, true));
      cancelEvents.forEach((eventName) => target.addEventListener(eventName, handleCancel, true));
    });

    return () => {
      targets.forEach((target) => {
        releaseEvents.forEach((eventName) => target.removeEventListener(eventName, handleRelease, true));
        cancelEvents.forEach((eventName) => target.removeEventListener(eventName, handleCancel, true));
      });
      cancelEditorPointerInteraction();
    };
  }, [cancelEditorPointerInteraction, ready, rememberManualEditorSize]);

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
    callTextAction(actions.onPreview, GUIDED_REVIEW_TRIBECA_KEY, editValue, false);
  };

  if (perImage) {
    return (
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
        <div id="guided-section-apply" className="acx-guided-review__image-cards">
          {scenario.pressPhotos.map((photo) => {
            const draft = guidedReviewDraftFor(reviewState, photo.key);
            if (draft === null) {
              return null;
            }
            return (
              <GuidedImageReviewCard
                key={photo.key}
                photo={photo}
                state={reviewState}
                draft={draft}
                actions={actions}
                scope={scope}
                {...(recordedOriginLabel !== undefined ? { recordedOriginLabel } : {})}
              />
            );
          })}
        </div>
      </section>
    );
  }

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
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => callImageAction(actions.onRetryFixture, GUIDED_REVIEW_TRIBECA_KEY, false)}
            >
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
              onPointerCancel={cancelEditorPointerInteraction}
              onMouseDown={beginEditorPointerInteraction}
              onMouseUp={rememberManualEditorSize}
              onTouchStart={beginEditorPointerInteraction}
              onTouchEnd={rememberManualEditorSize}
              onTouchCancel={cancelEditorPointerInteraction}
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
              <button
                type="button"
                className="acx-button acx-button--tertiary"
                onClick={() => callImageAction(actions.onKeep, GUIDED_REVIEW_TRIBECA_KEY, false)}
              >
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
            <button
              type="button"
              className="acx-button acx-button--tertiary"
              onClick={() => callImageAction(actions.onKeep, GUIDED_REVIEW_TRIBECA_KEY, false)}
            >
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
                        onClick={() =>
                          callRestoreAction(
                            actions.onRestore,
                            GUIDED_REVIEW_TRIBECA_KEY,
                            revision.revisionId,
                            'full',
                            false,
                          )
                        }
                      >
                        {guidedCopy('draft.restore_revision')}
                      </button>
                    ) : (
                      <>
                        <p>{guidedCopy('draft.restore_guard')}</p>
                        <button
                          type="button"
                          className="acx-button acx-button--tertiary"
                          onClick={() =>
                            callRestoreAction(
                              actions.onRestore,
                              GUIDED_REVIEW_TRIBECA_KEY,
                              revision.revisionId,
                              'copy_only',
                              false,
                            )
                          }
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
            onClick={() => callTextAction(actions.onApply, GUIDED_REVIEW_TRIBECA_KEY, editValue, false)}
            disabled={!applyEnabled}
            aria-describedby={!applyEnabled && reason ? 'guided-apply-reason' : undefined}
          >
            {guidedCopy('apply.submit')}
          </button>
          <button
            type="button"
            className="acx-button acx-button--tertiary"
            data-testid="demo-undo"
            onClick={() => callImageAction(actions.onUndo, GUIDED_REVIEW_TRIBECA_KEY, false)}
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

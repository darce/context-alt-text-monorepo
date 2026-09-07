import React, { useEffect, useMemo, useState } from 'react';

import {
  GUIDED_HISTORY_KIND,
  GUIDED_IDENTITY_STATUS,
  applyGuidedCandidate,
  confirmGuidedIdentity,
  confirmedPersonKeys,
  createGuidedScenario,
  getGuidedFace,
  getLastGuidedApplication,
  getGuidedPerson,
  leaveGuidedIdentityUnidentified,
  rejectGuidedCandidate,
  saveGuidedEdit,
  undoGuidedApplication,
  type GuidedHistoryEvent,
  type GuidedIdentityStatus,
  type GuidedPersonKey,
  type GuidedScenario,
} from '../../guidedPrototype/state';
import { GuidedPrototypeEntrance } from '../GuidedPrototypeEntrance';
import { getGuidedLiveMediaId } from '../../api/config';
import { GuidedDescriptionReview } from './GuidedDescriptionReview';
import { GuidedFacesPanel } from './GuidedFacesPanel';
import {
  focusGuidedSection,
  guidedStepLabel,
  GuidedPrototypeGuide,
  type GuidedGuideStep,
} from './GuidedPrototypeGuide';
import { GuidedResetDialog } from './GuidedResetDialog';
import { GuidedSamplePhoto } from './GuidedSamplePhoto';

const initialScenario = (): GuidedScenario => createGuidedScenario();

const assertNever = (value: never): never => {
  throw new Error(`Unexpected guided value: ${String(value)}`);
};

const isIdentityDecided = (status: GuidedIdentityStatus): boolean => {
  switch (status) {
    case GUIDED_IDENTITY_STATUS.CONFIRMED:
    case GUIDED_IDENTITY_STATUS.UNIDENTIFIED:
      return true;
    case GUIDED_IDENTITY_STATUS.UNCONFIRMED:
      return false;
    default:
      return assertNever(status);
  }
};

const assertHistoryFaceId: (
  event: GuidedHistoryEvent,
) => asserts event is GuidedHistoryEvent & { faceId: GuidedPersonKey } = (event) => {
  if (!event.faceId) {
    throw new Error('Guided identity history event is missing a face id.');
  }
};

const historyLabel = (scenario: GuidedScenario, event: GuidedHistoryEvent): string => {
  switch (event.kind) {
    case GUIDED_HISTORY_KIND.IDENTITY_CONFIRMED: {
      assertHistoryFaceId(event);
      const face = getGuidedFace(scenario, event.faceId);
      const person = getGuidedPerson(scenario, face.matchedPersonKey);
      return `You confirmed the face match: ${person.name}.`;
    }
    case GUIDED_HISTORY_KIND.IDENTITY_UNIDENTIFIED: {
      assertHistoryFaceId(event);
      const face = getGuidedFace(scenario, event.faceId);
      return `You kept the person on the ${face.position} unnamed.`;
    }
    case GUIDED_HISTORY_KIND.EDIT_SAVED:
      return 'You saved an edit.';
    case GUIDED_HISTORY_KIND.REJECTED:
      return 'You rejected the draft. The saved text did not change.';
    case GUIDED_HISTORY_KIND.APPLIED:
      return 'You applied the draft to the practice copy.';
    case GUIDED_HISTORY_KIND.APPLICATION_UNDONE:
      return 'You undid the apply.';
    default:
      return assertNever(event.kind);
  }
};

export const GuidedPrototypePage = (): React.JSX.Element => {
  const [scenario, setScenario] = useState<GuidedScenario>(initialScenario);
  const [guideOpen, setGuideOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<GuidedGuideStep>('understand');
  const [feedback, setFeedback] = useState('');
  const [resetVersion, setResetVersion] = useState(0);
  const [hasUnsavedEdit, setHasUnsavedEdit] = useState(false);
  const allIdentityDecisionsMade = scenario.identities.every((identity) => isIdentityDecided(identity.status));
  const flowIdentityState = allIdentityDecisionsMade ? 'done' : 'now';
  const flowDescriptionState = !allIdentityDecisionsMade
    ? 'waiting'
    : confirmedPersonKeys(scenario).length > 0
      ? 'done'
      : 'skipped';
  const matchedPeople = scenario.faces
    .map((face) => getGuidedPerson(scenario, face.matchedPersonKey).name)
    .join(' and ');
  const peopleOnFile = scenario.people
    .map((person) => `${person.name} (${person.savedPhotoCount} saved photos)`)
    .join(' · ');

  const historyLabels = useMemo(
    () =>
      scenario.history.map((event, index) => {
        return { id: `${event.kind}-${index}`, label: historyLabel(scenario, event) };
      }),
    [scenario],
  );

  useEffect(() => {
    const editor = document.getElementById('guided-description-draft');
    if (!(editor instanceof HTMLTextAreaElement)) {
      return;
    }

    // The review owns the textarea state; mirror its DOM value here so the
    // sibling faces panel can keep identity answers locked during an edit.
    const updateUnsavedEdit = (): void => {
      setHasUnsavedEdit(editor.value !== scenario.candidate.text);
    };
    const interactionRoot = editor.closest('.acx-guided-review');
    if (!(interactionRoot instanceof HTMLElement)) {
      return;
    }

    let syncTimer: number | undefined;
    const scheduleUnsavedEditUpdate = (): void => {
      if (syncTimer !== undefined) {
        window.clearTimeout(syncTimer);
      }
      syncTimer = window.setTimeout(() => {
        syncTimer = undefined;
        updateUnsavedEdit();
      }, 0);
    };
    editor.addEventListener('input', updateUnsavedEdit);
    editor.addEventListener('change', updateUnsavedEdit);
    interactionRoot.addEventListener('click', scheduleUnsavedEditUpdate);
    setHasUnsavedEdit(false);

    return () => {
      editor.removeEventListener('input', updateUnsavedEdit);
      editor.removeEventListener('change', updateUnsavedEdit);
      interactionRoot.removeEventListener('click', scheduleUnsavedEditUpdate);
      if (syncTimer !== undefined) {
        window.clearTimeout(syncTimer);
      }
    };
  }, [scenario.candidate.text, resetVersion]);

  const beginGuide = (): void => {
    setGuideOpen(true);
    setActiveStep('understand');
    setFeedback('The steps are open. Start with the photo.');
  };

  const handleGuideToggle = (): void => {
    setGuideOpen((current) => !current);
  };

  const handleGuideSelect = (step: GuidedGuideStep): void => {
    setActiveStep(step);
    setFeedback(`Now on: ${guidedStepLabel(step)}.`);
  };

  const handleGuideEnd = (): void => {
    setGuideOpen(false);
    setFeedback('Steps closed. You can keep practising.');
    focusGuidedSection('understand');
  };

  const updateScenario = (
    operation: (current: GuidedScenario) => GuidedScenario,
    message: string,
    step?: GuidedGuideStep,
    announceError = true,
  ): string | undefined => {
    try {
      // Evaluate the operation in the event handler so a domain validation error
      // can be shown in the single page feedback channel rather than escaping a
      // React state updater during render.
      const nextScenario = operation(scenario);
      setScenario(nextScenario);
      setFeedback(message);
      if (step) {
        setActiveStep(step);
      }
      return undefined;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unable to update this practice scenario.';
      setFeedback(announceError ? errorMessage : '');
      return errorMessage;
    }
  };

  const handleSaveEdit = (text: string): string | undefined => {
    return updateScenario(
      (current) => saveGuidedEdit(current, text),
      'Your edit is saved and ready to check.',
      'review',
      false,
    );
  };

  const handleApply = (): void => {
    updateScenario((current) => applyGuidedCandidate(current), 'Applied to the practice copy.', 'apply');
  };

  const resetPractice = (): void => {
    setScenario(initialScenario());
    setResetVersion((current) => current + 1);
    setHasUnsavedEdit(false);
    setActiveStep('understand');
    setFeedback('Practice reset. The original text is back.');
  };

  const handleConfirmIdentity = (faceId: GuidedPersonKey): void => {
    const face = getGuidedFace(scenario, faceId);
    const person = getGuidedPerson(scenario, face.matchedPersonKey);
    updateScenario(
      (current) => confirmGuidedIdentity(current, faceId),
      `Match confirmed. ${person.name} is in the draft. Nothing is applied yet.`,
      'review',
    );
    focusGuidedSection('review');
  };

  const handleLeaveUnidentified = (faceId: GuidedPersonKey): void => {
    const face = getGuidedFace(scenario, faceId);
    updateScenario(
      (current) => leaveGuidedIdentityUnidentified(current, faceId),
      `The person on the ${face.position} stays unnamed. You can still check the description.`,
      'review',
    );
    focusGuidedSection('review');
  };

  const handleReject = (): void => {
    updateScenario(
      (current) => rejectGuidedCandidate(current),
      'Draft rejected. The saved text did not change.',
      'review',
    );
    focusGuidedSection('review');
  };

  const handleUndo = (): void => {
    if (!getLastGuidedApplication(scenario.history)) {
      return;
    }

    updateScenario((current) => undoGuidedApplication(current), 'Apply undone.', 'apply');
    focusGuidedSection('apply');
  };

  return (
    <main className="acx-guided-page" aria-labelledby="acx-guided-entrance-title">
      <GuidedPrototypeEntrance onBegin={beginGuide} />
      <GuidedPrototypeGuide
        activeStep={activeStep}
        open={guideOpen}
        onToggle={handleGuideToggle}
        onSelect={handleGuideSelect}
        onEnd={handleGuideEnd}
      />

      <section className="acx-guided-page__workspace" aria-labelledby="acx-guided-page-title">
        <header className="acx-guided-page__hero">
          <div>
            <p className="acx-guided-page__eyebrow">Saved run</p>
            <h2 id="acx-guided-page-title">How two faces become two names in the description</h2>
            <p>
              AltContext looks at the photo, finds each face, and checks it against people you already named. If you
              confirm a match, that name goes into the description. You always have the last word.
            </p>
          </div>
          <GuidedResetDialog onConfirm={resetPractice} />
        </header>

        <div className="acx-guided-flow">
          <ol aria-label="How the faces reach the description">
            <li data-state="done">
              <span>Photo</span>
              <span className="acx-guided-flow__state">[done]</span>
            </li>
            <li data-state="done">
              <span>2 faces found</span>
              <span className="acx-guided-flow__state">[done]</span>
            </li>
            <li data-state="done">
              <span>Matched to {matchedPeople}</span>
              <span className="acx-guided-flow__state">[done]</span>
            </li>
            <li data-state={flowIdentityState}>
              <span>You confirm each match</span>
              <span className="acx-guided-flow__state">[{flowIdentityState}]</span>
            </li>
            <li data-state={flowDescriptionState}>
              <span>Names in the description</span>
              <span className="acx-guided-flow__state">[{flowDescriptionState}]</span>
            </li>
          </ol>
        </div>

        <section
          id="guided-section-understand"
          className="acx-guided-page__scenario"
          aria-label="Photo and page"
          tabIndex={-1}
        >
          <GuidedSamplePhoto
            src={scenario.pressPhoto.src}
            altText={scenario.drafts.none}
            currentAltText={scenario.pressPhoto.altText}
            credit={scenario.pressPhoto.credit}
          />
          <div className="acx-guided-page__provenance">
            <h3>Where this example comes from</h3>
            <dl>
              <div>
                <dt>Example</dt>
                <dd>Saved from a real run on 2026-09-06, not a live run</dd>
              </div>
              <div>
                <dt>Page</dt>
                <dd>{scenario.pageContext.title}</dd>
              </div>
              <div>
                <dt>People on file</dt>
                <dd>{peopleOnFile}</dd>
              </div>
              <div>
                <dt>Photo credit</dt>
                <dd>{scenario.pressPhoto.credit}</dd>
              </div>
              <div>
                <dt>Also checked</dt>
                <dd>{scenario.provenance.alsoChecked}</dd>
              </div>
            </dl>
          </div>
        </section>

        <GuidedFacesPanel
          scenario={scenario}
          hasUnsavedEdit={hasUnsavedEdit}
          onConfirm={handleConfirmIdentity}
          onLeaveUnnamed={handleLeaveUnidentified}
        />

        <p className="acx-guided-page__feedback" data-testid="guided-page-feedback" role="status" aria-live="polite">
          {feedback}
        </p>

        <GuidedDescriptionReview
          scenario={scenario}
          liveMediaId={getGuidedLiveMediaId()}
          resetVersion={resetVersion}
          onSaveEdit={handleSaveEdit}
          onReject={handleReject}
          onApply={handleApply}
          onUndo={handleUndo}
        />

        <section className="acx-guided-history" aria-labelledby="acx-guided-history-title">
          <div>
            <p className="acx-guided-page__eyebrow">What you did</p>
            <h2 id="acx-guided-history-title">Your decisions</h2>
          </div>
          {historyLabels.length === 0 ? (
            <p>Nothing yet. Your next action will show up here.</p>
          ) : (
            <ol>
              {historyLabels.map((event) => (
                <li key={event.id}>{event.label}</li>
              ))}
            </ol>
          )}
        </section>
      </section>
    </main>
  );
};

GuidedPrototypePage.displayName = 'GuidedPrototypePage';

import React, { useMemo, useState } from 'react';

import {
  applyGuidedCandidate,
  confirmGuidedIdentity,
  createGuidedScenario,
  leaveGuidedIdentityUnidentified,
  rejectGuidedCandidate,
  saveGuidedEdit,
  undoGuidedApplication,
  type GuidedScenario,
} from '../../guidedPrototype/state';
import { GuidedPrototypeEntrance } from '../GuidedPrototypeEntrance';
import { GuidedDescriptionReview } from './GuidedDescriptionReview';
import {
  focusGuidedSection,
  guidedStepLabel,
  GuidedPrototypeGuide,
  type GuidedGuideStep,
} from './GuidedPrototypeGuide';
import { GuidedResetDialog } from './GuidedResetDialog';
import { GuidedSamplePhoto } from './GuidedSamplePhoto';

const initialScenario = (): GuidedScenario => createGuidedScenario();

export const GuidedPrototypePage = (): React.JSX.Element => {
  const [scenario, setScenario] = useState<GuidedScenario>(initialScenario);
  const [guideOpen, setGuideOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<GuidedGuideStep>('understand');
  const [feedback, setFeedback] = useState('');
  const [resetVersion, setResetVersion] = useState(0);
  const identityUnconfirmed = scenario.identity.status === 'unconfirmed';
  const flowIdentityState = identityUnconfirmed ? 'now' : 'done';
  const flowDescriptionState = identityUnconfirmed
    ? 'waiting'
    : scenario.identity.status === 'confirmed'
      ? 'done'
      : 'skipped';

  const historyLabels = useMemo(
    () =>
      scenario.history.map((event, index) => {
        const labels: Record<typeof event.kind, string> = {
          'identity-confirmed': `You confirmed the face match: ${scenario.sourceRecord.name}.`,
          'identity-unidentified': 'You kept the person unnamed.',
          'edit-saved': 'You saved an edit.',
          rejected: 'You rejected the draft. The saved text did not change.',
          applied: 'You applied the draft to the practice copy.',
          'application-undone': 'You undid the apply.',
        };
        return { id: `${event.kind}-${index}`, label: labels[event.kind] };
      }),
    [scenario.history, scenario.sourceRecord.name],
  );

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
    setActiveStep('understand');
    setFeedback('Practice reset. The original text is back.');
  };

  const handleConfirmIdentity = (): void => {
    updateScenario(
      (current) => confirmGuidedIdentity(current),
      'Match confirmed. The name is in the draft. Nothing is applied yet.',
      'review',
    );
  };

  const handleLeaveUnidentified = (): void => {
    updateScenario(
      (current) => leaveGuidedIdentityUnidentified(current),
      'The person stays unnamed. You can still check the description.',
      'review',
    );
  };

  const handleReject = (): void => {
    updateScenario(
      (current) => rejectGuidedCandidate(current),
      'Draft rejected. The saved text did not change.',
      'review',
    );
  };

  const handleUndo = (): void => {
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
            <p className="acx-guided-page__eyebrow">Saved example</p>
            <h2 id="acx-guided-page-title">How a face becomes a name in the description</h2>
            <p>
              AltContext looks at the photo, finds a face, and checks it against people you already named. If you confirm
              the match, the name goes into the description. You always have the last word.
            </p>
          </div>
          <GuidedResetDialog onConfirm={resetPractice} />
        </header>

        <div className="acx-guided-flow">
          <ol aria-label="How the face reaches the description">
            <li data-state="done">
              <span>Photo</span>
              <span className="acx-guided-flow__state">[done]</span>
            </li>
            <li data-state="done">
              <span>Face found</span>
              <span className="acx-guided-flow__state">[done]</span>
            </li>
            <li data-state="done">
              <span>Matched to {scenario.faceMatch.matchedPersonName}</span>
              <span className="acx-guided-flow__state">[done]</span>
            </li>
            <li data-state={flowIdentityState}>
              <span>You confirm</span>
              <span className="acx-guided-flow__state">[{flowIdentityState}]</span>
            </li>
            <li data-state={flowDescriptionState}>
              <span>Name in the description</span>
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
          <GuidedSamplePhoto mediaAltText={scenario.originalMedia.altText} credit={scenario.sourceRecord.credit} />
          <div className="acx-guided-page__provenance">
            <h3>Where this example comes from</h3>
            <dl>
              <div>
                <dt>Example</dt>
                <dd>Saved example, not a live run</dd>
              </div>
              <div>
                <dt>Page</dt>
                <dd>{scenario.pageContext.title}</dd>
              </div>
              <div>
                <dt>Person on file</dt>
                <dd>{scenario.sourceRecord.name} · photo credit {scenario.sourceRecord.credit}</dd>
              </div>
            </dl>
          </div>
        </section>

        <p className="acx-guided-page__feedback" role="status" aria-live="polite">
          {feedback}
        </p>

        <GuidedDescriptionReview
          scenario={scenario}
          resetVersion={resetVersion}
          onConfirmIdentity={handleConfirmIdentity}
          onLeaveUnidentified={handleLeaveUnidentified}
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

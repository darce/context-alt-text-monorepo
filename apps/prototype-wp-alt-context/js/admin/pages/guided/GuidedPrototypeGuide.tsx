import React, { useEffect, useRef } from 'react';

export type GuidedGuideStep = 'understand' | 'face' | 'identity' | 'review' | 'apply';

interface GuidedGuideStepDefinition {
  id: GuidedGuideStep;
  label: string;
  description: string;
}

export const GUIDE_STEPS: readonly GuidedGuideStepDefinition[] = [
  { id: 'understand', label: 'Look at the photo', description: 'See the photo and the page it sits on.' },
  {
    id: 'face',
    label: 'Find the faces',
    description: 'AltContext found two faces and matched each one to a person you named before.',
  },
  { id: 'identity', label: 'Confirm each match', description: 'Say yes to each match, or keep that person unnamed.' },
  { id: 'review', label: 'Check the description', description: 'Read the draft. Edit it or reject it.' },
  { id: 'apply', label: 'Apply it yourself', description: 'Nothing changes until you press Apply.' },
];

export const guidedStepLabel = (step: GuidedGuideStep): string =>
  GUIDE_STEPS.find((definition) => definition.id === step)?.label ?? step;

export const GUIDED_SECTION_IDS: Record<GuidedGuideStep, string> = {
  understand: 'guided-section-understand',
  face: 'guided-section-face',
  identity: 'guided-section-identity',
  review: 'guided-section-review',
  apply: 'guided-section-apply',
};

export const focusGuidedSection = (step: GuidedGuideStep): void => {
  const target = document.getElementById(GUIDED_SECTION_IDS[step]);
  if (!target) {
    return;
  }

  const prefersReducedMotion =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  target.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start' });
  target.focus();
};

export interface GuidedPrototypeGuideProps {
  activeStep: GuidedGuideStep;
  open: boolean;
  onToggle: () => void;
  onSelect: (step: GuidedGuideStep) => void;
  onEnd: () => void;
}

export const GuidedPrototypeGuide = ({
  activeStep,
  open,
  onToggle,
  onSelect,
  onEnd,
}: GuidedPrototypeGuideProps): React.JSX.Element => {
  const activeDefinition = GUIDE_STEPS.find((step) => step.id === activeStep) ?? GUIDE_STEPS[0];
  const focusTargetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      focusTargetRef.current?.focus();
    }
  }, [open]);

  return (
    <nav className="acx-guided-guide" aria-label="Guided review steps">
      <div className="acx-guided-guide__bar">
        <div>
          <p className="acx-guided-guide__eyebrow">Step by step</p>
          <strong>{activeDefinition.label}</strong>
        </div>
        <a
          className="acx-guided-guide__skip-link"
          href={`#${GUIDED_SECTION_IDS[activeStep]}`}
          onClick={(event) => {
            event.preventDefault();
            focusGuidedSection(activeStep);
          }}
        >
          Skip to this step
        </a>
        <button
          type="button"
          className="acx-button acx-button--secondary acx-guided-guide__toggle"
          aria-expanded={open}
          onClick={onToggle}
        >
          {open ? 'Hide steps' : 'Show steps'}
        </button>
      </div>
      <div
        ref={focusTargetRef}
        className="acx-guided-guide__status"
        tabIndex={open ? -1 : undefined}
        data-guided-focus-target={open ? 'true' : undefined}
      >
        {activeDefinition.description}
      </div>
      {open ? (
        <div className="acx-guided-guide__body">
          <ol>
            {GUIDE_STEPS.map((step, index) => {
              const isCurrent = step.id === activeStep;
              return (
                <li key={step.id} className={isCurrent ? 'is-current' : undefined}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(step.id);
                      focusGuidedSection(step.id);
                    }}
                    aria-current={isCurrent ? 'step' : undefined}
                    aria-controls={GUIDED_SECTION_IDS[step.id]}
                  >
                    <span aria-hidden="true">{index + 1}</span>
                    <span>
                      <strong>{step.label}</strong>
                      <small>{step.description}</small>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          <button type="button" className="acx-button acx-button--tertiary" onClick={onEnd}>
            Close the steps
          </button>
        </div>
      ) : null}
    </nav>
  );
};

GuidedPrototypeGuide.displayName = 'GuidedPrototypeGuide';

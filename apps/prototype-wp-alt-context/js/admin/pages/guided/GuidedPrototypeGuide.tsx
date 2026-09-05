import React, { useEffect, useRef } from 'react';

export type GuidedGuideStep = 'understand' | 'identity' | 'review' | 'apply';

interface GuidedGuideStepDefinition {
  id: GuidedGuideStep;
  label: string;
  description: string;
}

const GUIDE_STEPS: readonly GuidedGuideStepDefinition[] = [
  { id: 'understand', label: 'Understand the context', description: 'See the image, page, and source record.' },
  { id: 'identity', label: 'Confirm identity', description: 'Use the sample record or leave the person unidentified.' },
  { id: 'review', label: 'Review the description', description: 'Edit or reject the identity-informed draft.' },
  { id: 'apply', label: 'Apply deliberately', description: 'Write only after you choose Apply.' },
];

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
          <p className="acx-guided-guide__eyebrow">Inline guide</p>
          <strong>{activeDefinition.label}</strong>
        </div>
        <button
          type="button"
          className="acx-button acx-button--secondary acx-guided-guide__toggle"
          aria-expanded={open}
          onClick={onToggle}
        >
          {open ? 'Hide guide' : 'Show guide'}
        </button>
      </div>
      <div
        ref={focusTargetRef}
        className="acx-guided-guide__status"
        role="status"
        aria-live="polite"
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
                  <button type="button" onClick={() => onSelect(step.id)} aria-current={isCurrent ? 'step' : undefined}>
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
            End guide
          </button>
        </div>
      ) : null}
    </nav>
  );
};

GuidedPrototypeGuide.displayName = 'GuidedPrototypeGuide';

import React from 'react';

export interface GuidedPrototypeEntranceProps {
  onBegin: () => void;
}

export const GuidedPrototypeEntrance = ({ onBegin }: GuidedPrototypeEntranceProps): React.JSX.Element => (
  <section className="acx-guided-entrance" aria-labelledby="acx-guided-entrance-title">
    <div className="acx-guided-entrance__brand" aria-label="AltContext">
      <span className="acx-guided-entrance__mark" aria-hidden="true">
        AC
      </span>
      <span>AltContext</span>
    </div>
    <p className="acx-guided-entrance__eyebrow">Guided demo</p>
    <h1 id="acx-guided-entrance-title">AltContext guided demo</h1>
    <p className="acx-guided-entrance__intro">
      Follow one photo from start to finish. AltContext finds two faces, matches each one to a person you already named,
      and puts their names in the image description. You choose what gets saved.
    </p>

    <div className="acx-guided-entrance__status">
      <strong>Current build</strong>
      <span>This demo uses one saved run. It does not run recognition live.</span>
    </div>

    <button type="button" className="acx-button acx-button--primary" onClick={onBegin}>
      Start the demo
    </button>

    <p className="acx-guided-entrance__boundary">
      This is a practice copy. Changes stay in this tab and reset when you reload the page. Live recognition and guest
      access are still in progress.
      <a
        className="acx-button acx-button--secondary acx-guided-entrance__case-study"
        href="https://darce.xyz/projects/altcontext/"
        target="_blank"
        rel="noreferrer"
      >
        Read the AltContext case study
      </a>
      .
    </p>
  </section>
);

GuidedPrototypeEntrance.displayName = 'GuidedPrototypeEntrance';

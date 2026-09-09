import React from 'react';

import { guidedCopy } from '../guidedPrototype/copy';

const CASE_STUDY_HREF = 'https://darce.xyz/projects/altcontext/';

export interface GuidedPrototypeEntranceProps {
  onBegin: () => void;
}

export const GuidedPrototypeEntrance = ({ onBegin }: GuidedPrototypeEntranceProps): React.JSX.Element => (
  <section className="acx-guided-entrance" aria-labelledby="acx-guided-entrance-title">
    <p className="acx-guided-entrance__eyebrow">{guidedCopy('page.eyebrow')}</p>
    <h1 id="acx-guided-entrance-title">{guidedCopy('page.title')}</h1>
    <p className="acx-guided-entrance__intro">{guidedCopy('page.intro')}</p>
    <p className="acx-guided-entrance__scope">{guidedCopy('page.scope')}</p>
    <p className="acx-guided-entrance__live-scope">{guidedCopy('page.live_scope')}</p>

    <button type="button" className="acx-button acx-button--primary" onClick={onBegin}>
      {guidedCopy('page.start')}
    </button>

    <p className="acx-guided-entrance__boundary">
      <a className="acx-guided-entrance__case-study" href={CASE_STUDY_HREF} target="_blank" rel="noreferrer">
        {guidedCopy('page.case_study')}
        <span className="screen-reader-text"> (opens in a new window)</span>
      </a>
    </p>
  </section>
);

GuidedPrototypeEntrance.displayName = 'GuidedPrototypeEntrance';

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { GuidedPrototypePage } from '../pages/guided/GuidedPrototypePage';
import { CASE_STUDY_URL, guidedCopy } from './copy';
import { RecordedWalkthrough } from './RecordedWalkthrough';

const PUBLIC_SCOPE =
  'Try the review workflow using a recorded example. Your changes affect only the demo copy in this tab.';
const START_WALKTHROUGH = 'Start the walkthrough';
const WATCH_RECORDING = 'Watch the recording';
const READ_CASE_STUDY = 'Read the case study';

describe('RecordedWalkthrough extraction', () => {
  it('renders the recorded walkthrough without a live panel by default', () => {
    render(<RecordedWalkthrough scope="admin" />);

    expect(screen.getByTestId('guided-demo-root')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.queryByTestId('guided-live')).not.toBeInTheDocument();
  });

  it('renders an optional live panel slot when provided', () => {
    render(
      <RecordedWalkthrough scope="admin" livePanel={<div data-testid="guided-live-slot">live</div>} />,
    );

    expect(screen.getByTestId('guided-live-slot')).toBeInTheDocument();
  });

  it('keeps GuidedPrototypePage as the admin composition with the live panel', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByTestId('guided-demo-root')).toBeInTheDocument();
    expect(screen.getByTestId('guided-live')).toBeInTheDocument();
  });
});

describe('RecordedWalkthrough public scope', () => {
  it('exports the case-study URL from copy', () => {
    expect(CASE_STUDY_URL).toBe('https://darce.github.io/');
    expect(guidedCopy('scope.public')).toBe(PUBLIC_SCOPE);
  });

  it('renders public scope copy first, the escape hatch, and the three entry actions', () => {
    render(<RecordedWalkthrough scope="public" escapeHref="https://example.test/" />);

    const scope = screen.getByTestId('guided-scope');
    expect(scope.tagName).toBe('P');
    expect(scope).toHaveTextContent(PUBLIC_SCOPE);

    const entrance = document.querySelector('.acx-guided-entrance');
    expect(entrance?.querySelector('p')).toBe(scope);

    const escape = screen.getByRole('navigation', { name: 'Leave the walkthrough' });
    expect(escape.querySelector('a[href="https://example.test/"]')).not.toBeNull();
    expect(escape.querySelector(`a[href="${CASE_STUDY_URL}"]`)).not.toBeNull();

    expect(screen.getByRole('button', { name: START_WALKTHROUGH })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: WATCH_RECORDING })).toHaveAttribute('href', CASE_STUDY_URL);
    expect(screen.getByRole('link', { name: READ_CASE_STUDY })).toHaveAttribute('href', CASE_STUDY_URL);
  });

  it('reaches Start, Watch, then Read by Tab in that order', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    const start = screen.getByRole('button', { name: START_WALKTHROUGH });
    start.focus();
    expect(document.activeElement).toBe(start);

    await user.tab();
    expect(document.activeElement).toHaveAccessibleName(WATCH_RECORDING);

    await user.tab();
    expect(document.activeElement).toHaveAccessibleName(READ_CASE_STUDY);
  });

  it('keeps admin entrance copy and the existing case-study link', () => {
    render(<RecordedWalkthrough scope="admin" />);

    expect(screen.queryByTestId('guided-scope')).not.toBeInTheDocument();
    expect(screen.getByText(guidedCopy('page.scope'))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('page.live_scope'))).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Leave the walkthrough' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: WATCH_RECORDING })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: READ_CASE_STUDY })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: new RegExp(`${guidedCopy('page.case_study')}.*opens in a new window`, 'i') })).toHaveAttribute(
      'href',
      'https://darce.xyz/projects/altcontext/',
    );
  });
});


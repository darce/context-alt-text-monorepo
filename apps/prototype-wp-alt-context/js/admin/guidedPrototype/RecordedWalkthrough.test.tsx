import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { GuidedPrototypePage } from '../pages/guided/GuidedPrototypePage';
import { CASE_STUDY_URL, RECORDING_URL, guidedCopy } from './publicGuideCopy';
import { RecordedWalkthrough } from './RecordedWalkthrough';

const PUBLIC_SCOPE =
  'Try the review workflow using a recorded example. Your changes affect only the demo copy in this tab.';
const START_WALKTHROUGH = 'Start the walkthrough';
const WATCH_RECORDING = 'Watch the recording';
const READ_CASE_STUDY = 'Read the case study';
const CANONICAL_CASE_STUDY_URL = 'https://darce.xyz/projects/altcontext/';
const opensInNewWindow = (label: string): string => `${label} (opens in a new window)`;

describe('RecordedWalkthrough extraction', () => {
  it('renders the recorded walkthrough without a live panel by default', () => {
    render(<RecordedWalkthrough scope="admin" />);

    expect(screen.getByTestId('guided-demo-root')).toBeInTheDocument();
    expect(screen.getByTestId('guided-demo-root').tagName).toBe('MAIN');
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
    expect(CASE_STUDY_URL).toBe(CANONICAL_CASE_STUDY_URL);
    expect(CASE_STUDY_URL).not.toContain('github.io');
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
    expect(screen.getByRole('link', { name: opensInNewWindow(WATCH_RECORDING) })).toHaveAttribute(
      'href',
      RECORDING_URL,
    );
    expect(screen.getByRole('link', { name: opensInNewWindow(READ_CASE_STUDY) })).toHaveAttribute(
      'href',
      CASE_STUDY_URL,
    );
  });

  it('gives every public entry action a distinct destination', () => {
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    expect(RECORDING_URL).not.toBe(CASE_STUDY_URL);
    expect(RECORDING_URL.startsWith(CASE_STUDY_URL)).toBe(true);

    const watch = screen.getByRole('link', { name: opensInNewWindow(WATCH_RECORDING) });
    const read = screen.getByRole('link', { name: opensInNewWindow(READ_CASE_STUDY) });
    const caseStudyNav = screen.getByRole('link', { name: opensInNewWindow(guidedCopy('nav.case_study')) });
    const start = screen.getByRole('button', { name: START_WALKTHROUGH });

    const actionLinks = Array.from(document.querySelectorAll('.acx-guided-entrance__actions a'));
    const actionHrefs = actionLinks.map((link) => link.getAttribute('href'));
    expect(actionHrefs).toEqual([RECORDING_URL, CASE_STUDY_URL]);
    expect(new Set(actionHrefs).size).toBe(actionHrefs.length);

    expect(watch).toHaveAttribute('href', RECORDING_URL);
    expect(read).toHaveAttribute('href', CASE_STUDY_URL);
    expect(caseStudyNav).toHaveAttribute('href', CASE_STUDY_URL);
    expect(start).not.toHaveAttribute('href');
  });

  it('opens public case-study and recording exits in a new tab and keeps Home in-tab', () => {
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    const watch = screen.getByRole('link', { name: opensInNewWindow(WATCH_RECORDING) });
    const read = screen.getByRole('link', { name: opensInNewWindow(READ_CASE_STUDY) });
    const escape = screen.getByRole('navigation', { name: guidedCopy('nav.leave') });
    const caseStudyNav = within(escape).getByRole('link', {
      name: opensInNewWindow(guidedCopy('nav.case_study')),
    });
    const home = within(escape).getByRole('link', { name: guidedCopy('nav.home') });

    for (const link of [watch, read, caseStudyNav]) {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link.getAttribute('rel') ?? '').toContain('noreferrer');
      expect(link).toHaveAccessibleName(/opens in a new window/i);
    }

    expect(home).not.toHaveAttribute('target', '_blank');
    expect(home.getAttribute('rel') ?? '').not.toContain('noreferrer');
    expect(home).toHaveAccessibleName(guidedCopy('nav.home'));
    expect(home).not.toHaveAccessibleName(/opens in a new window/i);
  });

  it('reaches Start, Watch, then Read by Tab in that order', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" escapeHref="/" />);

    const start = screen.getByRole('button', { name: START_WALKTHROUGH });
    start.focus();
    expect(document.activeElement).toBe(start);

    await user.tab();
    expect(document.activeElement).toHaveAccessibleName(opensInNewWindow(WATCH_RECORDING));

    await user.tab();
    expect(document.activeElement).toHaveAccessibleName(opensInNewWindow(READ_CASE_STUDY));
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
      CANONICAL_CASE_STUDY_URL,
    );
    expect(CASE_STUDY_URL).toBe(CANONICAL_CASE_STUDY_URL);
  });
});

describe('RecordedWalkthrough design notes', () => {
  it('hides live-generation copy on the public surface and keeps it for admin', () => {
    const { unmount } = render(<RecordedWalkthrough scope="public" escapeHref="/" />);
    expect(document.body.textContent ?? '').not.toContain('Live generation');
    unmount();

    render(<RecordedWalkthrough scope="admin" />);
    expect(document.body.textContent ?? '').toContain('Live generation');
  });
});


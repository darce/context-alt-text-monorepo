import { act } from 'react';
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { EmptyState, EMPTY_STATE_VARIANTS, EmptyStateVariant } from '../EmptyState';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

/**
 * DEMO-UX-1-D-6a: the shared dead-end guard.
 *
 * [NAV-08] every empty state carries a plain-language front-door action, so a
 * zero result is never a dead end.
 * [COG-01] copy is outcome-worded; the component never invents operator jargon.
 * [A11Y-24] both states are reachable and announced, not colour-only.
 */
describe('EmptyState (shared dead-end primitive)', () => {
  const FRONT_DOOR = { label: 'Run a scan', onClick: vi.fn() };

  it('renders the heading and the body', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No findings yet"
        body="Run a scan and new findings appear here automatically."
        action={FRONT_DOOR}
      />,
    );

    expect(screen.getByRole('heading', { name: 'No findings yet' })).toBeInTheDocument();
    expect(screen.getByText('Run a scan and new findings appear here automatically.')).toBeInTheDocument();
  });

  it('uses h3 as the default heading level [A11Y-24]', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No findings yet"
        body="Run a scan and new findings appear here automatically."
        action={FRONT_DOOR}
      />,
    );

    expect(screen.getByRole('heading', { level: 3, name: 'No findings yet' })).toBeInTheDocument();
  });

  it('honours the caller heading level so the surface keeps a valid outline [A11Y-24]', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No findings yet"
        body="Run a scan and new findings appear here automatically."
        action={FRONT_DOOR}
        headingLevel={2}
      />,
    );

    expect(screen.getByRole('heading', { level: 2, name: 'No findings yet' })).toBeInTheDocument();
  });

  // --- (b) an action is REQUIRED ------------------------------------------
  // This is the whole finding: 32 surfaces shipped a zero state with no way
  // out. The guard has to hold at BOTH levels — the type makes the dead end
  // uncompilable, the render proves the control actually reaches the DOM.

  it.each(EMPTY_STATE_VARIANTS)('renders an actionable control for variant "%s" [NAV-08]', (variant) => {
    render(
      <EmptyState
        variant={variant}
        heading="Face assignments unavailable"
        body="We could not load the review queue."
        action={{ label: 'Try again', onClick: vi.fn() }}
      />,
    );

    const region = screen.getByTestId('acx-empty-state');
    const control = within(region).getByRole('button', { name: 'Try again' });

    expect(control).toBeInTheDocument();
    expect(within(region).getAllByRole('button')).toHaveLength(1);
  });

  it('runs the front-door action on click, so the way out is real not decorative', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No people yet"
        body="Name a face and the person appears here."
        action={{ label: 'Name a face', onClick }}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Name a face' }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('accepts a link front door so a zero state can point at another screen [NAV-08]', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No media selected"
        body="Pick images in the library and they show up here."
        action={{ label: 'Open the media library', href: '/wp-admin/upload.php' }}
      />,
    );

    const link = screen.getByRole('link', { name: 'Open the media library' });

    expect(link).toHaveAttribute('href', '/wp-admin/upload.php');
  });

  it('makes a no-action EmptyState a TypeScript error (type-level guard for (b))', () => {
    // These render fine at runtime — the assertion is that `tsc --noEmit` reports
    // an error on each line below. If `action` ever becomes optional, or an inert
    // action (no onClick, no href) becomes assignable, TypeScript reports the
    // directive itself as unused and the typecheck fails. That is the guard.
    const missingAction = (
      // @ts-expect-error - `action` is required: a dead-end empty state must not compile.
      <EmptyState variant={EmptyStateVariant.EMPTY} heading="Dead end" body="No way out." />
    );

    const inertAction = (
      // @ts-expect-error - an action needs either `onClick` or `href`; a bare label is not a way out.
      <EmptyState variant={EmptyStateVariant.EMPTY} heading="Dead end" body="No way out." action={{ label: 'Go' }} />
    );

    const ambiguousAction = (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="Dead end"
        body="No way out."
        // @ts-expect-error - an action cannot navigate and run an in-place callback at the same time.
        action={{ label: 'Go', href: '/wp-admin/', onClick: vi.fn() }}
      />
    );

    expect(missingAction).toBeTruthy();
    expect(inertAction).toBeTruthy();
    expect(ambiguousAction).toBeTruthy();
  });

  // --- (c) ZERO is not BROKEN ---------------------------------------------
  // The shipped string 'Face assignments unavailable — this is not an empty
  // backlog.' already models the distinction. Encode it in the primitive so no
  // caller can re-flatten an outage into "all caught up".

  it('marks variant "empty" as a zero state, not a failure', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No findings yet"
        body="Run a scan and new findings appear here automatically."
        action={FRONT_DOOR}
      />,
    );

    const region = screen.getByTestId('acx-empty-state');

    expect(region).toHaveAttribute('data-variant', 'empty');
    expect(region.className).toContain('acx-empty-state--empty');
    expect(region).not.toHaveAttribute('role', 'status');
  });

  it('mounts an empty persistent live region, then announces the unavailable state [A11Y-24]', async () => {
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);

    flushSync(() => {
      root.render(
        <EmptyState
          variant={EmptyStateVariant.UNAVAILABLE}
          heading="Face assignments unavailable — this is not an empty backlog."
          body="We could not load the review queue."
          action={{ label: 'Try again', onClick: vi.fn() }}
        />,
      );
    });

    const region = container.querySelector('[data-testid="acx-empty-state"]');
    const liveRegion = container.querySelector('[role="status"]');
    const initialLiveText = liveRegion?.textContent;

    await act(() => Promise.resolve());

    const announcedLiveText = liveRegion?.textContent;

    act(() => root.unmount());
    container.remove();

    expect(region).toHaveAttribute('data-variant', 'unavailable');
    expect(region).toHaveClass('acx-empty-state--unavailable');
    expect(region).not.toHaveAttribute('role');
    expect(liveRegion).toHaveAttribute('aria-live', 'polite');
    expect(initialLiveText).toBe('');
    expect(announcedLiveText).toBe('Could not load');
  });

  it.each([
    [EmptyStateVariant.EMPTY, 'inbox'],
    [EmptyStateVariant.UNAVAILABLE, 'alert-triangle'],
  ] as const)('renders the expected icon for variant "%s"', (variant, iconName) => {
    render(<EmptyState variant={variant} heading="State heading" body="State body." action={FRONT_DOOR} />);

    expect(screen.getByTestId('acx-empty-state-icon')).toHaveAttribute('data-icon', iconName);
  });

  it('gives the two variants different rendered treatment, not just different copy', () => {
    const { unmount } = render(
      <EmptyState variant={EmptyStateVariant.EMPTY} heading="Same words" body="Same body." action={FRONT_DOOR} />,
    );
    const emptyClass = screen.getByTestId('acx-empty-state').className;
    const emptyIconKind = screen.getByTestId('acx-empty-state-icon').getAttribute('data-icon');
    unmount();

    render(
      <EmptyState variant={EmptyStateVariant.UNAVAILABLE} heading="Same words" body="Same body." action={FRONT_DOOR} />,
    );
    const unavailableClass = screen.getByTestId('acx-empty-state').className;
    const unavailableIconKind = screen.getByTestId('acx-empty-state-icon').getAttribute('data-icon');

    expect(emptyClass).not.toEqual(unavailableClass);
    // sr-004: a status indicator never leans on colour alone — the glyph differs too.
    expect(emptyIconKind).not.toEqual(unavailableIconKind);
  });

  it('pairs the glyph with a text equivalent, since the icon is aria-hidden [A11Y-24] [sr-004]', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.UNAVAILABLE}
        heading="Face assignments unavailable"
        body="We could not load the review queue."
        action={{ label: 'Try again', onClick: vi.fn() }}
      />,
    );

    expect(screen.getByTestId('acx-empty-state-icon')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByTestId('acx-empty-state-status-label')).toHaveTextContent('Could not load');
    expect(screen.getByTestId('acx-empty-state-status-label')).toHaveClass('screen-reader-text');
  });

  it('omits the internal live region when the host already owns the status channel', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No media matches your search."
        body="Clear the search to return to the media library."
        action={{ label: 'Clear search', onClick: vi.fn() }}
        announceState={false}
      />,
    );

    expect(screen.getByTestId('acx-empty-state')).toBeInTheDocument();
    expect(screen.queryByTestId('acx-empty-state-live-region')).not.toBeInTheDocument();
  });

  it('labels the region by its heading so assistive tech names it [A11Y-24]', () => {
    render(
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading="No findings yet"
        body="Run a scan and new findings appear here automatically."
        action={FRONT_DOOR}
      />,
    );

    const region = screen.getByTestId('acx-empty-state');
    const headingId = screen.getByRole('heading', { name: 'No findings yet' }).getAttribute('id');

    expect(headingId).toBeTruthy();
    expect(region).toHaveAttribute('aria-labelledby', headingId);
  });

  // --- sr-007: one canonical variant source -------------------------------

  it('exposes exactly the two variants from one as-const source [sr-007]', () => {
    expect(EMPTY_STATE_VARIANTS).toEqual(['empty', 'unavailable']);
    expect(Object.values(EmptyStateVariant)).toEqual(['empty', 'unavailable']);
  });
});

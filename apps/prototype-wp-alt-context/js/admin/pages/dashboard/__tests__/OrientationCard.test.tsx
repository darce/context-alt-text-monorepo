import { fireEvent, render, screen } from '@testing-library/react';

import { OrientationCard } from '../OrientationCard';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('OrientationCard', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.userSettings = { uid: '7' };
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete window.userSettings;
  });

  it('renders getting-started content independently of a detected-people count', () => {
    render(<OrientationCard />);

    expect(
      screen.getByRole('heading', { level: 2, name: 'Getting Started with Identity Recognition' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Start your first scan' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('uses the shipped Scan, Confirm, and Review stages without implementation vocabulary', () => {
    const { container } = render(<OrientationCard />);

    expect(screen.getByRole('heading', { level: 3, name: '1. Scan' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '2. Confirm' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '3. Review' })).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/cluster|embedding|mathematical identit/i);
  });

  it('persists explicit dismissal for only the current user', () => {
    const { unmount } = render(<OrientationCard />);

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss getting started' }));
    expect(
      screen.queryByRole('heading', { name: 'Getting Started with Identity Recognition' }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem('acx-orientation-dismissed:7')).toBe('true');
    unmount();

    render(<OrientationCard />);
    expect(
      screen.queryByRole('heading', { name: 'Getting Started with Identity Recognition' }),
    ).not.toBeInTheDocument();
    unmount();

    window.userSettings = { uid: '8' };
    render(<OrientationCard />);
    expect(screen.getByRole('heading', { name: 'Getting Started with Identity Recognition' })).toBeInTheDocument();
  });

  it('moves focus to the dashboard heading when dismissed', () => {
    render(
      <>
        <h1 id="acx-dashboard-title" tabIndex={-1}>
          Overview
        </h1>
        <OrientationCard />
      </>,
    );
    const dismissButton = screen.getByRole('button', { name: 'Dismiss getting started' });
    dismissButton.focus();

    fireEvent.click(dismissButton);

    expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Overview' }));
  });

  it('renders when localStorage reads throw', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('Storage unavailable');
    });

    expect(() => render(<OrientationCard />)).not.toThrow();
    expect(screen.getByRole('heading', { name: 'Getting Started with Identity Recognition' })).toBeInTheDocument();
  });

  it('dismisses and restores focus when localStorage writes throw', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('Storage unavailable');
    });
    render(
      <>
        <h1 id="acx-dashboard-title" tabIndex={-1}>
          Overview
        </h1>
        <OrientationCard />
      </>,
    );

    expect(() => fireEvent.click(screen.getByRole('button', { name: 'Dismiss getting started' }))).not.toThrow();
    expect(screen.queryByRole('button', { name: 'Dismiss getting started' })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('heading', { level: 1, name: 'Overview' }));
  });
});

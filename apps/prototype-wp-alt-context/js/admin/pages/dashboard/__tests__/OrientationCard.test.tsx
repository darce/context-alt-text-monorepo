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
    delete window.userSettings;
  });

  it('renders getting-started content independently of a detected-people count', () => {
    render(<OrientationCard />);

    expect(screen.getByRole('heading', { name: 'Getting Started with Identity Recognition' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Start your first scan' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('uses the shipped Scan, Confirm, and Review stages without implementation vocabulary', () => {
    const { container } = render(<OrientationCard />);

    expect(screen.getByRole('heading', { name: '1. Scan' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '2. Confirm' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '3. Review' })).toBeInTheDocument();
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

    window.userSettings = { uid: '8' };
    render(<OrientationCard />);
    expect(screen.getByRole('heading', { name: 'Getting Started with Identity Recognition' })).toBeInTheDocument();
  });
});

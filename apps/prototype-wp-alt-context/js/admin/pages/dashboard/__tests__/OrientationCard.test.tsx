import { render, screen } from '@testing-library/react';

import { OrientationCard } from '../OrientationCard';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

describe('OrientationCard', () => {
  it('renders getting-started content when peopleCount is 0', () => {
    render(<OrientationCard peopleCount={0} />);

    expect(screen.getByRole('heading', { name: 'Getting Started with Identity Recognition' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Start your first scan' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('remains available when the site already has people', () => {
    render(<OrientationCard peopleCount={1} />);

    expect(screen.getByRole('heading', { name: 'Getting Started with Identity Recognition' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Workbench' })).toHaveAttribute('href', '#/workbench?tab=scan');
  });

  it('uses the shipped Scan, Confirm, and Review stages without implementation vocabulary', () => {
    const { container } = render(<OrientationCard peopleCount={0} />);

    expect(screen.getByRole('heading', { name: '1. Scan' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '2. Confirm' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '3. Review' })).toBeInTheDocument();
    expect(container).not.toHaveTextContent(/cluster|embedding|mathematical identit/i);
  });

  it('does not use localStorage dismissal state', () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    render(<OrientationCard peopleCount={0} />);

    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Dismiss orientation|Got it/i })).not.toBeInTheDocument();

    getItem.mockRestore();
    setItem.mockRestore();
  });
});

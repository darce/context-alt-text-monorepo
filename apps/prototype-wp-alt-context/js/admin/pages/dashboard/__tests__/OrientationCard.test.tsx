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

  it('renders nothing when peopleCount is greater than 0', () => {
    const { container } = render(<OrientationCard peopleCount={1} />);

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('heading', { name: 'Getting Started with Identity Recognition' })).not.toBeInTheDocument();
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

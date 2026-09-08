import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StepMap, STEP_MAP_VALUES } from '../StepMap';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) =>
    format.replace(/%(\d+)\$[ds]/g, (_match: string, position: string) => String(args[Number(position) - 1])),
}));

describe('StepMap', () => {
  const steps = [
    { id: STEP_MAP_VALUES.scan, label: 'Scan', onSelect: vi.fn() },
    { id: STEP_MAP_VALUES.confirm, label: 'Confirm', onSelect: vi.fn() },
    { id: STEP_MAP_VALUES.review, label: 'Review' },
  ] as const;

  it('maps the ordered flow, current position, completed steps, and remaining steps without color alone', () => {
    render(<StepMap activeStep={STEP_MAP_VALUES.confirm} steps={steps} />);

    const nav = screen.getByRole('navigation', { name: 'Progress' });
    const list = screen.getByRole('list');
    const items = screen.getAllByRole('listitem');

    expect(nav).toBeInTheDocument();
    expect(list.tagName).toBe('OL');
    expect(list).not.toHaveAccessibleName('Progress');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('Scan');
    expect(items[0]).toHaveTextContent('Completed');
    expect(items[1]).toHaveTextContent('Confirm');
    expect(items[1]).toHaveTextContent('Current');
    expect(items[1]).toHaveAttribute('aria-current', 'step');
    expect(items[2]).toHaveTextContent('Review');
    expect(items[2]).toHaveTextContent('Remaining');
    expect(screen.getByRole('status')).toHaveTextContent('Step 2 of 3: Confirm');
  });

  it('renders without throwing when activeStep is absent from steps', () => {
    render(
      <StepMap
        activeStep={STEP_MAP_VALUES.review}
        steps={[
          { id: STEP_MAP_VALUES.scan, label: 'Scan' },
          { id: STEP_MAP_VALUES.confirm, label: 'Confirm' },
        ]}
      />,
    );

    expect(screen.getByRole('navigation', { name: 'Progress' })).toBeInTheDocument();
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Scan');
    expect(items[0]).toHaveTextContent('Remaining');
    expect(items[1]).toHaveTextContent('Confirm');
    expect(items[1]).toHaveTextContent('Remaining');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByTestId('acx-workbench-step-scan')).not.toHaveAttribute('aria-current');
    expect(screen.getByTestId('acx-workbench-step-confirm')).not.toHaveAttribute('aria-current');
  });

  it('keeps selectable steps re-enterable', async () => {
    const onSelectScan = vi.fn();
    const user = userEvent.setup();

    render(
      <StepMap
        activeStep={STEP_MAP_VALUES.review}
        steps={[
          { id: STEP_MAP_VALUES.scan, label: 'Scan', onSelect: onSelectScan },
          { id: STEP_MAP_VALUES.confirm, label: 'Confirm', onSelect: vi.fn() },
          { id: STEP_MAP_VALUES.review, label: 'Review' },
        ]}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Scan/ }));

    expect(onSelectScan).toHaveBeenCalledOnce();
  });
});

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

    const list = screen.getByRole('list', { name: 'Progress' });
    const items = screen.getAllByRole('listitem');

    expect(list.tagName).toBe('OL');
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

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { BetaExpectationsNotice } from '../BetaExpectationsNotice';
import { GPU_STATE_VOCABULARY } from '../gpuStatePresentation';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => `«${text}»`,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string) => format,
}));

describe('BetaExpectationsNotice', () => {
  it('discloses AI drafts without an alert and keeps expectations closed until requested', async () => {
    render(<BetaExpectationsNotice />);
    const notice = screen.getByTestId('beta-expectations-notice');
    expect(notice.firstElementChild).toHaveTextContent(
      '«Beta: descriptions are AI-generated drafts to review before publishing.»',
    );
    expect(within(notice).queryByRole('alert')).not.toBeInTheDocument();
    const details = notice.querySelector('details');
    expect(details).not.toHaveAttribute('open');
    const summary = screen.getByText('«What to expect»');
    expect(summary.tagName).toBe('SUMMARY');
    summary.focus();
    expect(summary).toHaveFocus();
    await userEvent.click(summary);
    expect(details).toHaveAttribute('open');
    expect(within(notice).getByText(GPU_STATE_VOCABULARY.coldStartWait)).toBeVisible();
    await userEvent.click(summary);
    expect(details).not.toHaveAttribute('open');
  });
});

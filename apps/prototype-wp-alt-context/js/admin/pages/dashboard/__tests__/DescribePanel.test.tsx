import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DescribePanel } from '../DescribePanel';

const mutate = vi.fn();
let offline = false;

interface HookState {
  mutate: typeof mutate;
  isPending: boolean;
  data: unknown;
  error: Error | null;
  reset: () => void;
}

let hookState: HookState;

vi.mock('../../../hooks/useDescribeMedia', () => ({
  useDescribeMedia: () => hookState,
}));

vi.mock('../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => offline,
}));

const sampleResult = {
  adapter: 'local_cpu',
  model_id: 'microsoft/Florence-2-base-ft',
  model_version: 'florence-2-base-ft',
  visual_facts: { caption: 'A red dahlia in bloom.', objects: ['flower', 'leaf'], ocr_text: null },
  alt_text_draft: 'A red dahlia in bloom.',
  cached: false,
  duration_ms: 13800,
};

const enterMediaId = (value: string) => {
  fireEvent.change(screen.getByLabelText(/attachment id/i), { target: { value } });
};

describe('DescribePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    offline = false;
    hookState = { mutate, isPending: false, data: undefined, error: null, reset: vi.fn() };
  });

  it('renders the Describe with AI control (empty: no attachment id)', () => {
    render(<DescribePanel />);
    const button = screen.getByRole('button', { name: /describe with ai/i });
    expect(button).toBeInTheDocument();
    expect(button).toBeDisabled();
  });

  it('submits the parsed numeric media id', () => {
    render(<DescribePanel />);
    enterMediaId('42');
    fireEvent.click(screen.getByRole('button', { name: /describe with ai/i }));
    expect(mutate).toHaveBeenCalledWith(42);
  });

  it('disables the control and shows progress copy while pending', () => {
    hookState = { ...hookState, isPending: true };
    render(<DescribePanel />);
    const button = screen.getByRole('button', { name: /describing/i });
    expect(button).toBeDisabled();
  });

  it('renders the alt text, visual facts and provenance on success', () => {
    hookState = { ...hookState, data: sampleResult };
    render(<DescribePanel />);
    expect(screen.getByText('A red dahlia in bloom.')).toBeInTheDocument();
    expect(screen.getByText(/flower/)).toBeInTheDocument();
    expect(screen.getByText(/Florence-2-base-ft/)).toBeInTheDocument();
  });

  it('surfaces the 503 stub reason on error', () => {
    hookState = {
      ...hookState,
      error: new Error(
        'Request to .../describe failed (503): {"detail":"description adapter unavailable: gpu_phi4 requires a GPU host."}',
      ),
    };
    render(<DescribePanel />);
    expect(screen.getByText(/requires a GPU host/i)).toBeInTheDocument();
  });

  it('disables submit with offline reason when breaker is open', () => {
    offline = true;
    render(<DescribePanel />);
    enterMediaId('42');
    const button = screen.getByRole('button', { name: /describe with ai/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
    expect(button).toHaveAttribute('aria-disabled', 'true');
    const reasonId = button.getAttribute('aria-describedby');
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId ?? '')).toHaveTextContent(
      'Unavailable while the recognition service is offline',
    );
  });

  it('gates form submit / Enter while offline (not button-only)', () => {
    offline = true;
    render(<DescribePanel />);
    enterMediaId('42');
    const form = screen.getByRole('button', { name: /describe with ai/i }).closest('form');
    expect(form).toBeTruthy();
    fireEvent.submit(form!);
    expect(mutate).not.toHaveBeenCalled();
  });

  it('allows form submit when online with a valid id', () => {
    render(<DescribePanel />);
    enterMediaId('7');
    const form = screen.getByRole('button', { name: /describe with ai/i }).closest('form');
    fireEvent.submit(form!);
    expect(mutate).toHaveBeenCalledWith(7);
  });
});

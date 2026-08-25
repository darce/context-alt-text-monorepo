import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useAriaAnnounce } from '../useAriaAnnounce';

const REPEAT = 'This review target is no longer available.';

const LiveHarness = ({
  announceRef,
  messages,
}: {
  announceRef: { current: ((message: string) => void) | null };
  messages: Array<string | null>;
}) => {
  const { message, seq, announce } = useAriaAnnounce();
  announceRef.current = announce;
  messages.push(message);
  return (
    <p role="status" aria-live="polite" data-testid="aria-live" data-announce-seq={seq}>
      {message}
    </p>
  );
};

const removedThenRestored = (records: MutationRecord[], copy: string): boolean => {
  const removed = records.some(
    (record) =>
      record.type === 'childList' &&
      Array.from(record.removedNodes).some((node) => (node.textContent ?? '') === copy),
  );
  const added = records.some(
    (record) =>
      record.type === 'childList' &&
      Array.from(record.addedNodes).some((node) => (node.textContent ?? '') === copy),
  );
  return removed && added;
};

describe('useAriaAnnounce', () => {
  it('DUX-W2R1-RV-03: identical repeat mutates a stable node empty-then-restore', async () => {
    const announceRef: { current: ((message: string) => void) | null } = { current: null };
    const messages: Array<string | null> = [];
    render(<LiveHarness announceRef={announceRef} messages={messages} />);
    const node = screen.getByTestId('aria-live');

    act(() => {
      announceRef.current?.(REPEAT);
    });
    await waitFor(() => expect(node).toHaveTextContent(REPEAT));

    const records: MutationRecord[] = [];
    const observer = new MutationObserver((batch) => {
      records.push(...batch);
    });
    observer.observe(node, { characterData: true, childList: true, subtree: true });
    const seq1 = node.getAttribute('data-announce-seq');
    const start = messages.length;

    act(() => {
      announceRef.current?.(REPEAT);
    });
    await waitFor(() => {
      expect(node).toHaveTextContent(REPEAT);
      expect(node.getAttribute('data-announce-seq')).not.toBe(seq1);
    });
    records.push(...observer.takeRecords());
    observer.disconnect();

    const after = messages.slice(start);
    expect(screen.getByTestId('aria-live')).toBe(node);
    expect(after).toContain(null);
    expect(after[after.length - 1]).toBe(REPEAT);
    expect(removedThenRestored(records, REPEAT)).toBe(true);
  });

  it('DUX-W2R1-RV-02: announce during clear phase stays in clear-then-set', async () => {
    const announceRef: { current: ((message: string) => void) | null } = { current: null };
    const messages: Array<string | null> = [];
    render(<LiveHarness announceRef={announceRef} messages={messages} />);
    const node = screen.getByTestId('aria-live');

    act(() => {
      announceRef.current?.(REPEAT);
    });
    await waitFor(() => expect(node).toHaveTextContent(REPEAT));

    const records: MutationRecord[] = [];
    const observer = new MutationObserver((batch) => {
      records.push(...batch);
    });
    observer.observe(node, { characterData: true, childList: true, subtree: true });
    const start = messages.length;

    act(() => {
      announceRef.current?.(REPEAT);
      announceRef.current?.(REPEAT);
    });
    await waitFor(() => expect(node).toHaveTextContent(REPEAT));
    records.push(...observer.takeRecords());
    observer.disconnect();

    const after = messages.slice(start);
    expect(screen.getByTestId('aria-live')).toBe(node);
    expect(after).toContain(null);
    expect(after[after.length - 1]).toBe(REPEAT);
    expect(removedThenRestored(records, REPEAT)).toBe(true);
  });
});

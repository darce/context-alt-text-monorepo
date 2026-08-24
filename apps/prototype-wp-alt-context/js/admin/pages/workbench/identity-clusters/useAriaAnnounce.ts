/**
 * A11Y-21 aria-live announce sink that re-fires on repeated identical strings.
 *
 * BR-68: a plain `useState<string>` bails out on an `Object.is`-equal set, so two
 * consecutive announcements with the same text (e.g. two sequential retirement
 * closes) never re-render the live region — a screen reader stays silent on the
 * second. The monotonic `seq` guarantees a fresh state object every announce.
 * Repeated copy first clears the persistent live-region content, then a follow-up
 * render inserts the message so it creates a DOM mutation without remounting the
 * region. New copy publishes immediately, preserving the hook's synchronous
 * single-announcement contract.
 */

import { useCallback, useEffect, useState } from 'react';

interface AriaAnnounceState {
  message: string | null;
  seq: number;
}

interface InternalAriaAnnounceState extends AriaAnnounceState {
  pendingMessage: string | null;
}

export interface UseAriaAnnounceResult extends AriaAnnounceState {
  /** Announce `message`; always forces a distinct render, even for a repeat. */
  announce: (message: string) => void;
}

export const useAriaAnnounce = (): UseAriaAnnounceResult => {
  const [state, setState] = useState<InternalAriaAnnounceState>({
    message: null,
    pendingMessage: null,
    seq: 0,
  });
  const announce = useCallback((message: string) => {
    setState((prev) =>
      prev.message === message
        ? { message: null, pendingMessage: message, seq: prev.seq + 1 }
        : { message, pendingMessage: null, seq: prev.seq + 1 },
    );
  }, []);

  useEffect(() => {
    if (state.pendingMessage === null) {
      return;
    }
    setState((current) => {
      if (current.seq !== state.seq || current.pendingMessage === null) {
        return current;
      }
      return { ...current, message: current.pendingMessage, pendingMessage: null };
    });
  }, [state.pendingMessage, state.seq]);

  return { message: state.message, seq: state.seq, announce };
};

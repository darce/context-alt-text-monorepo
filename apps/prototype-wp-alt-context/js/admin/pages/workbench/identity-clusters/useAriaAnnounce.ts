/**
 * A11Y-21 aria-live announce sink that re-fires on repeated identical strings.
 *
 * BR-68: a plain `useState<string>` bails out on an `Object.is`-equal set, so two
 * consecutive announcements with the same text (e.g. two sequential retirement
 * closes) never re-render the live region — a screen reader stays silent on the
 * second. The monotonic `seq` guarantees a fresh state object every announce.
 *
 * Callers that keep a stable live-region node (no `key={seq}`) still get a DOM
 * text mutation on every announce because this always writes a new state object.
 * Callers that remount on `seq` get a fresh region for free.
 */

import { useCallback, useState } from 'react';

interface AriaAnnounceState {
  message: string | null;
  seq: number;
}

export interface UseAriaAnnounceResult extends AriaAnnounceState {
  /** Announce `message`; always forces a distinct render, even for a repeat. */
  announce: (message: string) => void;
}

export const useAriaAnnounce = (): UseAriaAnnounceResult => {
  const [state, setState] = useState<AriaAnnounceState>({ message: null, seq: 0 });
  const announce = useCallback((message: string) => {
    setState((prev) => ({ message, seq: prev.seq + 1 }));
  }, []);
  return { message: state.message, seq: state.seq, announce };
};

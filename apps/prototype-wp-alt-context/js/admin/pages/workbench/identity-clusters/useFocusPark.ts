/**
 * BR-13 / BR-33: keep keyboard focus on a pending surface after native `disabled`
 * blurs the active control to `document.body`, without reclaiming focus that
 * another row (or page chrome) stranded.
 *
 * Each pending instance listens at the document for `focusout`, but only parks
 * when the event target was inside *this* container. Sibling rows' disable-blur
 * therefore cannot pull focus across instances, and a later accept-error restore
 * on another row is not defeated by a foreign park.
 */

import { useEffect } from 'react';

/** Minimal ref shape so callers can pass `useRef<HTMLDivElement>(null)` without casts. */
export interface FocusParkContainerRef {
  readonly current: HTMLElement | null;
}

export const useFocusPark = (isPending: boolean, containerRef: FocusParkContainerRef): void => {
  useEffect(() => {
    if (!isPending) {
      return;
    }

    const parkIfStranded = (event?: Event): void => {
      // Document-level focusout: only reclaim strands that left THIS container.
      // Without this origin check every pending instance claims any body-strand
      // on the page (BR-33).
      if (event) {
        const node = containerRef.current;
        if (!node) {
          return;
        }
        const target = event.target;
        if (!(target instanceof Node) || !node.contains(target)) {
          return;
        }
      }
      queueMicrotask(() => {
        const node = containerRef.current;
        if (!node) {
          return;
        }
        const active = document.activeElement;
        if (!active || active === document.body) {
          node.focus();
        }
      });
    };

    // Entering pending: catch same-turn disable-blur (and stand-ins that have
    // already dropped focus to body before the listener is attached).
    parkIfStranded();
    document.addEventListener('focusout', parkIfStranded);
    return () => {
      document.removeEventListener('focusout', parkIfStranded);
    };
  }, [isPending, containerRef]);
};

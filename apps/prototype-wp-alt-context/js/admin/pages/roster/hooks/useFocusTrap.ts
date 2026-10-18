import React from 'react';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface UseFocusTrapOptions {
  rootRef: React.RefObject<HTMLElement>;
  initialFocusRef?: React.RefObject<HTMLElement>;
  onEscape?: () => void;
  activeKey?: string | number | null;
}

export const useFocusTrap = ({
  rootRef,
  initialFocusRef,
  onEscape,
  activeKey,
}: UseFocusTrapOptions): ((event: React.KeyboardEvent<HTMLElement>) => void) => {
  React.useEffect(() => {
    if (activeKey === null || activeKey === undefined) {
      return;
    }
    initialFocusRef?.current?.focus();
  }, [activeKey, initialFocusRef]);

  return React.useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (event.key === 'Escape') {
        onEscape?.();
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const root = rootRef.current;
      if (!root) {
        return;
      }

      const focusables = root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      if (focusables.length === 0) {
        return;
      }

      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;

      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
        return;
      }

      if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onEscape, rootRef],
  );
};

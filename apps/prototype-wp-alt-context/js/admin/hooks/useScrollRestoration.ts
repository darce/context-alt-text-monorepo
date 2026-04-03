import { useLayoutEffect } from 'react';
import { useLocation } from 'react-router-dom';

export const useScrollRestoration = (componentKey: string): void => {
  const location = useLocation();
  const routeKey = `${location.pathname}${location.search}`;
  const storageKey = `scroll_pos_${routeKey}_${componentKey}`;

  useLayoutEffect(() => {
    const savedPos = sessionStorage.getItem(storageKey);
    // Use requestAnimationFrame to ensure the DOM is fully rendered before scrolling.
    // try/catch guards against throwing scrollTo implementations (e.g. jsdom).
    if (savedPos !== null) {
      window.requestAnimationFrame(() => {
        try {
          window.scrollTo(0, parseInt(savedPos, 10));
        } catch {
          /* partial DOM */
        }
      });
    } else {
      window.requestAnimationFrame(() => {
        try {
          window.scrollTo(0, 0);
        } catch {
          /* partial DOM */
        }
      });
    }

    return () => {
      // Save on unmount or route change
      sessionStorage.setItem(storageKey, (window.scrollY ?? 0).toString());
    };
  }, [storageKey]);
};

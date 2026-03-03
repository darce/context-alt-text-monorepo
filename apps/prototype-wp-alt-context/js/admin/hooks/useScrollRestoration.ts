import { useLayoutEffect } from 'react';
import { useLocation } from 'react-router-dom';

export const useScrollRestoration = (componentKey: string): void => {
  const location = useLocation();
  const routeKey = `${location.pathname}${location.search}`;
  const storageKey = `scroll_pos_${routeKey}_${componentKey}`;

  useLayoutEffect(() => {
    const savedPos = sessionStorage.getItem(storageKey);
    if (savedPos !== null) {
      // Use setTimeout to ensure the DOM is fully rendered before scrolling
      window.requestAnimationFrame(() => {
          window.scrollTo(0, parseInt(savedPos, 10));
      });
    } else {
      window.requestAnimationFrame(() => {
          window.scrollTo(0, 0);
      });
    }

    return () => {
      // Save on unmount or route change
      sessionStorage.setItem(storageKey, window.scrollY.toString());
    };
  }, [storageKey]);
};

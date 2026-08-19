import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

import { commitSearchParams } from './pendingSearchWrites';

export const useOverlayParam = <T extends string>(
  paramName: string,
  validValues: readonly T[],
): [T | null, (value: T | null) => void] => {
  const [searchParams, setSearchParams] = useSearchParams();

  const rawParam = searchParams.get(paramName);
  const activeOverlay = rawParam && validValues.includes(rawParam as T) ? (rawParam as T) : null;

  const setOverlay = useCallback(
    (value: T | null) => {
      commitSearchParams(setSearchParams, (next) => {
        if (value) {
          next.set(paramName, value);
        } else {
          next.delete(paramName);
        }
      });
    },
    [paramName, setSearchParams],
  );

  return [activeOverlay, setOverlay];
};

import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

import { commitSearchParams } from './pendingSearchWrites';

export const useTabParam = <T extends string>(
  paramName: string,
  defaultValue: T,
  validValues: readonly T[],
): [T, (value: T) => void] => {
  const [searchParams, setSearchParams] = useSearchParams();

  const rawParam = searchParams.get(paramName);
  const activeTab = rawParam && validValues.includes(rawParam as T) ? (rawParam as T) : defaultValue;

  const setTab = useCallback(
    (value: T) => {
      commitSearchParams(setSearchParams, (next) => {
        next.set(paramName, value);
      });
    },
    [paramName, setSearchParams],
  );

  return [activeTab, setTab];
};

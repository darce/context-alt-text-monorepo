import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

export const useTabParam = <T extends string>(
  paramName: string,
  defaultValue: T,
  validValues: readonly T[]
): [T, (value: T) => void] => {
  const [searchParams, setSearchParams] = useSearchParams();

  const rawParam = searchParams.get(paramName);
  const activeTab =
    rawParam && validValues.includes(rawParam as T) ? (rawParam as T) : defaultValue;

  const setTab = useCallback(
    (value: T) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set(paramName, value);
          return next;
        },
        { replace: true }
      );
    },
    [paramName, setSearchParams]
  );

  return [activeTab, setTab];
};

import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

import { getRouteParam, writeRosterFaceParam } from '../rosterRoute';

export const useRosterFaceRoute = (): {
  requestedFaceId: string | null;
  writeFace: (faceId: string | null, personUuid: string | null) => void;
} => {
  let searchParams: URLSearchParams;
  let setSearchParams: ReturnType<typeof useSearchParams>[1];

  try {
    [searchParams, setSearchParams] = useSearchParams();
  } catch {
    searchParams = new URLSearchParams();
    setSearchParams = ((next: URLSearchParams) => next) as ReturnType<typeof useSearchParams>[1];
  }

  const requestedFaceId = getRouteParam(searchParams, 'face');

  const writeFace = useCallback(
    (faceId: string | null, personUuid: string | null) => {
      setSearchParams((previous) => writeRosterFaceParam(previous, faceId, personUuid), { replace: true });
    },
    [setSearchParams],
  );

  return { requestedFaceId, writeFace };
};

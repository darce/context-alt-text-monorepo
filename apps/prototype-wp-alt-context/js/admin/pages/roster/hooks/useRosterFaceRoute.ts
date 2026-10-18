import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

import { APP_LINK_PARAMS } from '../../../navigation/appLinks';
import { getRouteParam, writeRosterFaceParam } from '../rosterRoute';

export const useRosterFaceRoute = (): {
  requestedFaceId: string | null;
  writeFace: (faceId: string | null, personUuid: string | null) => void;
} => {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedFaceId = getRouteParam(searchParams, APP_LINK_PARAMS.face);

  const writeFace = useCallback(
    (faceId: string | null, personUuid: string | null) => {
      setSearchParams((previous) => writeRosterFaceParam(previous, faceId, personUuid), { replace: true });
    },
    [setSearchParams],
  );

  return { requestedFaceId, writeFace };
};

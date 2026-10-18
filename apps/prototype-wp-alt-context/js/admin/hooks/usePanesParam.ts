import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

import { APP_LINK_PARAMS, parsePanes, serializePanes, type PanesState } from '../navigation/appLinks';
import { commitSearchParams } from './pendingSearchWrites';

export type { PanesState };

/**
 * Workbench two-pane collapse state via `?panes=`.
 * Default `'both'` omits the param; independent of overlay `?panel=` [NAV-11].
 */
export const usePanesParam = (): [PanesState, (value: PanesState) => void] => {
  const [searchParams, setSearchParams] = useSearchParams();

  const panes = parsePanes(searchParams.get(APP_LINK_PARAMS.panes));

  const setPanes = useCallback(
    (value: PanesState) => {
      commitSearchParams(setSearchParams, (next) => {
        const wire = serializePanes(value);
        if (wire === null) {
          next.delete(APP_LINK_PARAMS.panes);
        } else {
          next.set(APP_LINK_PARAMS.panes, wire);
        }
      });
    },
    [setSearchParams],
  );

  return [panes, setPanes];
};

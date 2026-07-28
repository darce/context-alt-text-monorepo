import { __ } from '@wordpress/i18n';
import { useEffect, useRef, useState } from 'react';

import { resolveDescribeErrorMessage } from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { useDescribeMedia } from '../../hooks/useDescribeMedia';

export interface MediaAltSuggestProps {
  mediaId: number;
}

export const MediaAltSuggest = ({ mediaId }: MediaAltSuggestProps): React.JSX.Element => {
  const [statusMessage, setStatusMessage] = useState('');
  const { mutate, isPending, isError, error, data, reset } = useDescribeMedia();
  const {
    mutate: acceptDraft,
    isPending: isAccepting,
    isError: isAcceptError,
    error: acceptError,
    reset: resetAccept,
  } = useCorrectMediaAlt();
  const suggestButtonRef = useRef<HTMLButtonElement>(null);
  const dismissButtonRef = useRef<HTMLButtonElement>(null);
  const retryButtonRef = useRef<HTMLButtonElement>(null);
  const shouldFocusSuggestRef = useRef(false);

  const generate = (): void => {
    setStatusMessage('');
    resetAccept();
    mutate(mediaId, {
      onSuccess: () => {
        setStatusMessage(__('Draft ready. Review before saving.', 'alt-context'));
      },
    });
  };

  // When a terminal mutation state mounts (error / draft / idle-after-dismiss),
  // the previously focused control has unmounted — restore focus to an actionable
  // control in the new branch so keyboard/SR users are not stranded on body
  // (WBUX-5-S2C-BR-01). Idle focus only when shouldFocusSuggestRef is set (Dismiss),
  // never on the initial mount.
  useEffect(() => {
    if (isError) {
      retryButtonRef.current?.focus();
    } else if (data) {
      dismissButtonRef.current?.focus();
    } else if (shouldFocusSuggestRef.current) {
      shouldFocusSuggestRef.current = false;
      suggestButtonRef.current?.focus();
    }
  }, [isError, data]);

  if (isPending) {
    return (
      <div className="acx-media-selection__media-alt-suggest">
        <button
          type="button"
          className="button acx-media-selection__media-alt-suggest-trigger"
          disabled
        >
          {__('Generating…', 'alt-context')}
        </button>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="acx-media-selection__media-alt-suggest">
        <div className="acx-media-selection__media-alt-error" role="alert">
          {resolveDescribeErrorMessage(
            error,
            __('Could not generate a draft. Please try again.', 'alt-context'),
          )}
        </div>
        <button
          type="button"
          ref={retryButtonRef}
          className="button acx-media-selection__media-alt-suggest-retry"
          onClick={generate}
        >
          {__('Try again', 'alt-context')}
        </button>
      </div>
    );
  }

  if (data) {
    const accept = (): void => {
      acceptDraft(
        { mediaId, altText: data.alt_text_draft },
        {
          onSuccess: () => {
            shouldFocusSuggestRef.current = true;
            setStatusMessage(__('Alt text saved.', 'alt-context'));
            reset();
          },
        },
      );
    };

    return (
      <div className="acx-media-selection__media-alt-suggest">
        <p className="acx-media-selection__media-alt-draft">{data.alt_text_draft}</p>
        <p className="acx-media-selection__media-alt-disclosure">
          {__('Drafted by AI — review before saving.', 'alt-context')}
        </p>
        {statusMessage ? (
          <div role="status" aria-live="polite" className="screen-reader-text">
            {statusMessage}
          </div>
        ) : null}
        {isAcceptError ? (
          <div className="acx-media-selection__media-alt-error" role="alert">
            {resolveDescribeErrorMessage(
              acceptError,
              __('Could not save the alt text. Please try again.', 'alt-context'),
            )}
          </div>
        ) : null}
        <button
          type="button"
          className="button button-primary acx-media-selection__media-alt-suggest-accept"
          onClick={accept}
          disabled={isAccepting}
        >
          {isAccepting ? __('Saving…', 'alt-context') : __('Accept', 'alt-context')}
        </button>
        <button
          type="button"
          ref={dismissButtonRef}
          className="button button-link acx-media-selection__media-alt-suggest-dismiss"
          onClick={() => {
            shouldFocusSuggestRef.current = true;
            reset();
            resetAccept();
            setStatusMessage('');
          }}
          disabled={isAccepting}
        >
          {__('Dismiss', 'alt-context')}
        </button>
      </div>
    );
  }

  return (
    <div className="acx-media-selection__media-alt-suggest">
      <button
        type="button"
        ref={suggestButtonRef}
        className="button acx-media-selection__media-alt-suggest-trigger"
        onClick={generate}
      >
        {__('Suggest alt text', 'alt-context')}
      </button>
      {statusMessage ? (
        <div role="status" aria-live="polite" className="screen-reader-text">
          {statusMessage}
        </div>
      ) : null}
    </div>
  );
};

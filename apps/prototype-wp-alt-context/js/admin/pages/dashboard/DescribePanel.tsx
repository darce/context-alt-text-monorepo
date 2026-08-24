import React, { useId, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { useDescribeMedia } from '../../hooks/useDescribeMedia';
import { useRemoteActionGate } from '../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../hooks/useSyncOffline';
import { resolveDescribeErrorMessage } from '../../api/describeApi';

/**
 * E19-1 S12: a self-contained "Describe with AI" tool. The operator enters an
 * attachment id (visible in the Media Library) and gets the backend visual-facts
 * draft for it. Drives the seeded / florence_small profiles; a deferred stub
 * profile (florence_large, gpu_phi4) returns a 503 whose reason is surfaced.
 */
export const DescribePanel = (): React.JSX.Element => {
  const inputId = useId();
  const unavailableReasonId = `${inputId}-unavailable-reason`;
  const [mediaIdInput, setMediaIdInput] = useState('');
  const mutation = useDescribeMedia();
  // RES-15/RES-03: fold offline into canSubmit + handleSubmit so Enter cannot bypass.
  const offline = useSyncOffline();
  const remoteGate = useRemoteActionGate(offline);

  const parsedId = Number.parseInt(mediaIdInput, 10);
  const hasValidId = Number.isInteger(parsedId) && parsedId > 0;
  const canSubmit = hasValidId && !mutation.isPending && !offline;

  const handleSubmit = (event: React.FormEvent): void => {
    event.preventDefault();
    if (canSubmit) {
      mutation.mutate(parsedId);
    }
  };

  // Hide the prior image's result/error while a new describe is in flight —
  // react-query keeps the last data/error during the next mutation (E19-1-REV-B-2).
  const result = mutation.isPending ? undefined : mutation.data;
  const errorMessage =
    !mutation.isPending && mutation.error
      ? resolveDescribeErrorMessage(
          mutation.error,
          __('The description service could not be reached. Try again.', 'alt-context'),
        )
      : null;

  return (
    <section className="acx-dashboard__panel acx-describe" aria-labelledby={`${inputId}-title`}>
      <h2 id={`${inputId}-title`}>{__('AI Image Description (preview)', 'alt-context')}</h2>
      <p>
        {__(
          'Generate a visual-facts draft for one image. Enter its attachment ID from the Media Library.',
          'alt-context',
        )}
      </p>

      <form className="acx-describe__form" onSubmit={handleSubmit}>
        <label htmlFor={inputId}>{__('Attachment ID', 'alt-context')}</label>
        <input
          id={inputId}
          type="number"
          min={1}
          inputMode="numeric"
          className="acx-input"
          value={mediaIdInput}
          onChange={(event) => setMediaIdInput(event.target.value)}
          placeholder={__('e.g. 42', 'alt-context')}
        />
        <button
          type="submit"
          className="acx-button acx-button--primary"
          disabled={!canSubmit}
          aria-disabled={remoteGate['aria-disabled']}
          aria-describedby={offline ? unavailableReasonId : undefined}
          title={remoteGate.title}
        >
          {mutation.isPending ? __('Describing…', 'alt-context') : __('Describe with AI', 'alt-context')}
        </button>
        {offline && remoteGate.title ? (
          <span id={unavailableReasonId} className="screen-reader-text">
            {remoteGate.title}
          </span>
        ) : null}
      </form>

      {errorMessage ? (
        <div className="acx-error-state" role="alert">
          <span aria-hidden="true">⚠</span> {errorMessage}
        </div>
      ) : null}

      {result ? (
        <div className="acx-describe__result" aria-live="polite">
          <h3>{__('Suggested alt text', 'alt-context')}</h3>
          <p className="acx-describe__alt-text">{result.alt_text_draft}</p>

          {result.visual_facts.caption && result.visual_facts.caption !== result.alt_text_draft ? (
            <p className="acx-describe__caption">{result.visual_facts.caption}</p>
          ) : null}

          {result.visual_facts.objects.length > 0 ? (
            <ul className="acx-describe__objects">
              {result.visual_facts.objects.map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
          ) : null}

          {result.visual_facts.ocr_text ? (
            <p className="acx-describe__ocr">
              {sprintf(__('Text in image: %s', 'alt-context'), result.visual_facts.ocr_text)}
            </p>
          ) : null}

          <dl className="acx-describe__provenance">
            <div>
              <dt>{__('Adapter', 'alt-context')}</dt>
              <dd>{result.adapter}</dd>
            </div>
            <div>
              <dt>{__('Model', 'alt-context')}</dt>
              <dd>
                {result.model_id} ({result.model_version})
              </dd>
            </div>
            <div>
              <dt>{__('Source', 'alt-context')}</dt>
              <dd>{result.cached ? __('Cached', 'alt-context') : __('Freshly generated', 'alt-context')}</dd>
            </div>
            <div>
              <dt>{__('Latency', 'alt-context')}</dt>
              <dd>{sprintf(__('%ss', 'alt-context'), (result.duration_ms / 1000).toFixed(1))}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </section>
  );
};

import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import type { RepeatedRegionEvidenceView, RepeatedRegionObservation } from './repeatedRegionEvidence';

const readHostUiCountLocale = (): string | null => {
  try {
    return typeof document === 'undefined' ? null : document.documentElement.lang || null;
  } catch {
    return null;
  }
};

type HumanCountLocale =
  | { kind: 'localized'; tag: string }
  | { kind: 'neutral-raw'; reason: 'missing' | 'invalid' | 'unsupported' | 'unavailable' };

const resolveHumanCountLocale = (raw: string | null): HumanCountLocale => {
  if (!raw?.trim()) {
    return { kind: 'neutral-raw', reason: 'missing' };
  }
  if (
    typeof Intl === 'undefined' ||
    typeof Intl.getCanonicalLocales !== 'function' ||
    typeof Intl.NumberFormat !== 'function' ||
    typeof Intl.NumberFormat.supportedLocalesOf !== 'function'
  ) {
    return { kind: 'neutral-raw', reason: 'unavailable' };
  }
  let tag: string | undefined;
  try {
    [tag] = Intl.getCanonicalLocales(raw.trim());
  } catch (error) {
    return { kind: 'neutral-raw', reason: error instanceof RangeError ? 'invalid' : 'unavailable' };
  }
  if (!tag) {
    return { kind: 'neutral-raw', reason: 'invalid' };
  }
  try {
    return Intl.NumberFormat.supportedLocalesOf([tag], { localeMatcher: 'lookup' }).includes(tag)
      ? { kind: 'localized', tag }
      : { kind: 'neutral-raw', reason: 'unsupported' };
  } catch {
    return { kind: 'neutral-raw', reason: 'unavailable' };
  }
};

const formatHumanCount = (count: number, uiLocale: string | null): string => {
  const locale = resolveHumanCountLocale(uiLocale);
  if (locale.kind === 'localized') {
    try {
      return new Intl.NumberFormat(locale.tag, { style: 'decimal', maximumFractionDigits: 0 }).format(count);
    } catch {
      // Deliberate neutral raw-numeric fallback; never the runtime default locale.
    }
  }
  return String(count);
};

// Keep references as React text nodes, including delimiters/markup in server IDs.
// Numbered gettext slots may reorder or repeat without interpolating IDs into HTML.
type ReferenceTemplate = ReturnType<
  typeof __<'Person %s' | 'Face group %s' | '%1$s (person %2$s)' | '%1$s (face group %2$s)' | '%1$s — face record %2$s'>
>;
const withReferences = (template: ReferenceTemplate, values: readonly React.ReactNode[]): React.JSX.Element => {
  const tokens = ['{acx-reference-0}', '{acx-reference-1}'] as const;
  const text = sprintf(template, tokens[0], tokens[1]);
  return (
    <>
      {text.split(/(\{acx-reference-[01]\})/).map((part, index) => (
        <React.Fragment key={index}>
          {part === tokens[0] ? values[0] : part === tokens[1] ? values[1] : part}
        </React.Fragment>
      ))}
    </>
  );
};

const groupReference = (
  observation: RepeatedRegionObservation,
  labels: RepeatedRegionEvidenceView['groupLabels'],
): React.JSX.Element => {
  const label = labels.get(observation.groupKey);
  if (observation.personId !== null) {
    const reference = <code>{observation.personId}</code>;
    return label
      ? withReferences(__('%1$s (person %2$s)', 'alt-context'), [label, reference])
      : withReferences(__('Person %s', 'alt-context'), [reference]);
  }
  if (observation.clusterId !== null) {
    const reference = <code>{observation.clusterId}</code>;
    return label
      ? withReferences(__('%1$s (face group %2$s)', 'alt-context'), [label, reference])
      : withReferences(__('Face group %s', 'alt-context'), [reference]);
  }
  return <>{__('Not yet grouped', 'alt-context')}</>;
};

/** In-place text evidence. References never enter the summary or any action name. */
export const RepeatedRegionEvidenceDisclosure = ({ view }: { view: RepeatedRegionEvidenceView }): React.JSX.Element => {
  const uiLocale = readHostUiCountLocale();
  const otherGroups = new Set(view.regions.flatMap((region) => region.groupKeys));
  otherGroups.delete(view.groupKey);
  const n = otherGroups.size;
  const { pool } = view;
  const skipped = pool.abstainedIdentityIds.length;
  return (
    <details className="acx-identity-cluster__repeated-region" data-testid="acx-repeated-region-evidence">
      <summary>
        {sprintf(
          _n(
            'Same photo region is also listed in %s other group',
            'Same photo region is also listed in %s other groups',
            n,
            'alt-context',
          ),
          formatHumanCount(n, uiLocale),
        )}
      </summary>
      <p>
        {__(
          'Matching uses exact box coordinates in the face records loaded for this photo. It does not show that these faces are the same person, and nothing is merged or moved.',
          'alt-context',
        )}
      </p>
      <ul>
        {view.regions.map((region) => (
          <li key={region.regionKey}>
            <p>
              {sprintf(
                __('Photo %1$d — box x %2$s, y %3$s, width %4$s, height %5$s', 'alt-context'),
                region.mediaId,
                String(region.bbox.x),
                String(region.bbox.y),
                String(region.bbox.width),
                String(region.bbox.height),
              )}
            </p>
            <ul>
              {region.observations.map((observation) => (
                <li key={observation.identityId}>
                  {withReferences(__('%1$s — face record %2$s', 'alt-context'), [
                    groupReference(observation, view.groupLabels),
                    <code key="record">{observation.identityId}</code>,
                  ])}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <p>
        {sprintf(
          _n(
            'Checked %1$s of %2$s loaded face record with usable box coordinates.',
            'Checked %1$s of %2$s loaded face records with usable box coordinates.',
            pool.loadedObservationCount,
            'alt-context',
          ),
          formatHumanCount(pool.eligibleObservationCount, uiLocale),
          formatHumanCount(pool.loadedObservationCount, uiLocale),
        )}
      </p>
      {skipped > 0 && (
        <p>
          {sprintf(
            _n(
              '%s face record was skipped because its loaded copies disagree.',
              '%s face records were skipped because their loaded copies disagree.',
              skipped,
              'alt-context',
            ),
            formatHumanCount(skipped, uiLocale),
          )}
        </p>
      )}
    </details>
  );
};

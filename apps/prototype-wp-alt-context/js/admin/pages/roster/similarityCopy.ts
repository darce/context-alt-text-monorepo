import { __ } from '@wordpress/i18n';

export const SIMILARITY_BAND = {
  STRONG: 'strong',
  LIKELY: 'likely',
  POSSIBLE: 'possible',
  WEAK: 'weak',
  PENDING: 'pending',
} as const;

export type SimilarityBand = (typeof SIMILARITY_BAND)[keyof typeof SIMILARITY_BAND];

interface EvidenceMetadata {
  similarity: number | null;
  similarity_threshold?: number | null;
}

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

export const classifySimilarity = (similarity: number | null | undefined): SimilarityBand => {
  if (!isFiniteNumber(similarity)) {
    return SIMILARITY_BAND.PENDING;
  }
  if (similarity >= 0.9) {
    return SIMILARITY_BAND.STRONG;
  }
  if (similarity >= 0.75) {
    return SIMILARITY_BAND.LIKELY;
  }
  if (similarity >= 0.6) {
    return SIMILARITY_BAND.POSSIBLE;
  }
  return SIMILARITY_BAND.WEAK;
};

const bandLabel = (band: SimilarityBand): string => {
  switch (band) {
    case SIMILARITY_BAND.STRONG:
      return __('strong match', 'alt-context');
    case SIMILARITY_BAND.LIKELY:
      return __('likely match', 'alt-context');
    case SIMILARITY_BAND.POSSIBLE:
      return __('possible match', 'alt-context');
    case SIMILARITY_BAND.WEAK:
      return __('weak match', 'alt-context');
    case SIMILARITY_BAND.PENDING:
      return __('Similarity pending next projection refresh.', 'alt-context');
    default: {
      const _exhaustive: never = band;
      return _exhaustive;
    }
  }
};

export const getSelectedFaceMetadataLines = (evidence: EvidenceMetadata | null | undefined): string[] => {
  if (!evidence) {
    return [];
  }

  const lines: string[] = [bandLabel(classifySimilarity(evidence.similarity))];

  if (isFiniteNumber(evidence.similarity)) {
    lines.push(__('Match evidence from the current face group', 'alt-context'));
    lines.push(__('Compared with selected person', 'alt-context'));
    lines.push(__('Higher is closer within this batch', 'alt-context'));
  }

  if (isFiniteNumber(evidence.similarity) && isFiniteNumber(evidence.similarity_threshold)) {
    lines.push(
      evidence.similarity >= evidence.similarity_threshold
        ? __('Above this face group’s current threshold', 'alt-context')
        : __('Below this face group’s current threshold', 'alt-context'),
    );
  }

  return lines;
};

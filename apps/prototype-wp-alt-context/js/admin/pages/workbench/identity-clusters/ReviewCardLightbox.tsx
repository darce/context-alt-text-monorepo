/**
 * Shim — implementation lives in js/components/ui/FaceLightbox.
 * Consumers (ReviewQueue.tsx, index.ts) keep importing ReviewCardLightbox unchanged.
 */

export {
  FaceLightbox as ReviewCardLightbox,
  type FaceLightboxProps as ReviewCardLightboxProps,
} from '../../../../components/ui/FaceLightbox';

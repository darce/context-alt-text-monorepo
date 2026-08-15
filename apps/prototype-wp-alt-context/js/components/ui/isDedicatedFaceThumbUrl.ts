/**
 * True when a thumb URL is a server-side face crop under recognition/face-thumbs/.
 * Those are already cropped — do not feed them through FaceThumbnail again.
 */
export const isDedicatedFaceThumbUrl = (thumbUrl: string | null | undefined): boolean => {
  return typeof thumbUrl === 'string' && thumbUrl.includes('recognition/face-thumbs/');
};

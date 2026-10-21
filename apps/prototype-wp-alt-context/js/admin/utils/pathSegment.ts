export class InvalidIdPathSegmentError extends Error {
  constructor() {
    super('Invalid ID path segment.');
    this.name = 'InvalidIdPathSegmentError';
  }
}

export const idPathSegment = (value: string): string => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value)) {
    throw new InvalidIdPathSegmentError();
  }
  return encodeURIComponent(value);
};

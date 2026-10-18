import { __ } from '@wordpress/i18n';

export const formatTimestamp = (value: string | null | undefined): string => {
  if (!value) {
    return __('Unknown time', 'alt-context');
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return __('Unknown time', 'alt-context');
  }

  return parsed.toLocaleString();
};

import { __ } from '@wordpress/i18n';

export const SOURCE_LABELS: Record<string, string> = {
  constant: __('Set via wp-config.php constant', 'alt-context'),
  option: __('Saved in database', 'alt-context'),
  filter: __('Provided by a code filter', 'alt-context'),
  default: __('Not configured', 'alt-context'),
};

export const isReadOnly = (source: string): boolean => source === 'constant' || source === 'filter';
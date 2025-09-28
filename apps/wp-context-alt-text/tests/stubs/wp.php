<?php

declare(strict_types=1);

if (!function_exists('add_action')) {
    function add_action($hook, $callback, $priority = 10, $accepted_args = 1): bool
    {
        return true;
    }
}

if (!function_exists('add_filter')) {
    function add_filter($hook, $callback, $priority = 10, $accepted_args = 1): bool
    {
        return true;
    }
}

if (!function_exists('admin_url')) {
    function admin_url(string $path = ''): string
    {
        return '/wp-admin/' . ltrim($path, '/');
    }
}

if (!function_exists('wp_nonce_url')) {
    function wp_nonce_url(string $url, string $action): string
    {
        $separator = str_contains($url, '?') ? '&' : '?';
        return $url . $separator . '_wpnonce=' . rawurlencode($action);
    }
}

if (!function_exists('esc_url')) {
    function esc_url($value)
    {
        return (string) $value;
    }
}

if (!function_exists('trailingslashit')) {
    function trailingslashit($value)
    {
        return rtrim((string) $value, '/\\') . '/';
    }
}

if (!function_exists('esc_attr')) {
    function esc_attr($value)
    {
        return (string) $value;
    }
}

if (!function_exists('esc_html')) {
    function esc_html($value)
    {
        return (string) $value;
    }
}

if (!function_exists('esc_html__')) {
    function esc_html__($value, $domain = null)
    {
        return (string) $value;
    }
}

if (!function_exists('esc_html_e')) {
    function esc_html_e($value, $domain = null): void
    {
        echo esc_html__($value, $domain);
    }
}

if (!function_exists('__')) {
    function __($value, $domain = null)
    {
        return (string) $value;
    }
}

if (!function_exists('is_admin')) {
    function is_admin(): bool
    {
        return true;
    }
}

if (!function_exists('wp_next_scheduled')) {
    function wp_next_scheduled($hook)
    {
        return $GLOBALS['__cat_scheduled'][$hook] ?? false;
    }
}

if (!function_exists('wp_schedule_single_event')) {
    function wp_schedule_single_event($timestamp, $hook): void
    {
        $GLOBALS['__cat_scheduled'][$hook] = $timestamp;
    }
}

if (!function_exists('wp_clear_scheduled_hook')) {
    function wp_clear_scheduled_hook($hook): void
    {
        unset($GLOBALS['__cat_scheduled'][$hook]);
    }
}

if (!function_exists('update_option')) {
    function update_option($key, $value)
    {
        $GLOBALS['__cat_options'][$key] = $value;
        return true;
    }
}

if (!function_exists('get_option')) {
    function get_option($key, $default = false)
    {
        return $GLOBALS['__cat_options'][$key] ?? $default;
    }
}

if (!function_exists('delete_option')) {
    function delete_option($key): void
    {
        unset($GLOBALS['__cat_options'][$key]);
    }
}

if (!function_exists('human_time_diff')) {
    function human_time_diff($from, $to = null): string
    {
        $to = $to ?? time();
        $diff = max((int) $to - (int) $from, 0);
        return $diff . ' seconds';
    }
}

if (!function_exists('apply_filters')) {
    function apply_filters($hook, $value)
    {
        return $value;
    }
}

if (!function_exists('number_format_i18n')) {
    function number_format_i18n($number, $decimals = 0)
    {
        return number_format((float) $number, (int) $decimals);
    }
}

if (!function_exists('wp_json_encode')) {
    function wp_json_encode($data)
    {
        return json_encode($data);
    }
}

if (!function_exists('wp_enqueue_script')) {
    function wp_enqueue_script($handle, $src = '', $deps = [], $ver = false, $in_footer = false): void
    {
        $GLOBALS['__cat_scripts'][$handle] = compact('src', 'deps', 'ver', 'in_footer');
    }
}

if (!function_exists('wp_enqueue_style')) {
    function wp_enqueue_style($handle, $src = '', $deps = [], $ver = false, $media = 'all'): void
    {
        $GLOBALS['__cat_styles'][$handle] = compact('src', 'deps', 'ver', 'media');
    }
}

if (!function_exists('wp_localize_script')) {
    function wp_localize_script($handle, $object_name, $l10n): void
    {
        $GLOBALS['__cat_localized_scripts'][$handle][$object_name] = $l10n;
    }
}

if (!function_exists('wp_get_environment_type')) {
    function wp_get_environment_type(): string
    {
        return $_ENV['WP_ENVIRONMENT_TYPE'] ?? 'production';
    }
}

if (!class_exists('WP_Query')) {
    class WP_Query
    {
        private array $vars = [];
        private bool $mainQuery;

        public function __construct(bool $mainQuery = true)
        {
            $this->mainQuery = $mainQuery;
        }

        public function is_main_query(): bool
        {
            return $this->mainQuery;
        }

        public function set($key, $value): void
        {
            $this->vars[$key] = $value;
        }

        public function get($key, $default = null)
        {
            return $this->vars[$key] ?? $default;
        }

        public function get_vars(): array
        {
            return $this->vars;
        }
    }
}

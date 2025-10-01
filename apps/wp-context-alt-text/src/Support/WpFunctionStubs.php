<?php

declare(strict_types=1);

if (!function_exists('plugin_dir_path')) {
    function plugin_dir_path(string $file): string
    {
        return rtrim(dirname($file), '/\\') . '/';
    }
}

if (!function_exists('plugin_dir_url')) {
    function plugin_dir_url(string $file): string
    {
        return plugin_dir_path($file);
    }
}

if (!function_exists('plugin_basename')) {
    function plugin_basename(string $file): string
    {
        $pluginRoot = defined('WP_PLUGIN_DIR') ? WP_PLUGIN_DIR : dirname($file);
        return trim(str_replace(rtrim($pluginRoot, '/\\') . '/', '', $file), '/');
    }
}

if (!function_exists('get_file_data')) {
    /**
     * Minimal get_file_data implementation for non-WordPress environments.
     *
     * @param array<string,string> $defaultHeaders
     * @return array<string,string>
     */
    function get_file_data(string $file, array $defaultHeaders, string $context = ''): array
    {
        unset($context);

        $data = array_fill_keys(array_keys($defaultHeaders), '');

        if (!is_readable($file)) {
            return $data;
        }

        $fileData = file_get_contents($file, false, null, 0, 8192);
        if ($fileData === false) {
            return $data;
        }

        foreach ($defaultHeaders as $key => $header) {
            $pattern = '/^[ \t\/*#@]*' . preg_quote($header, '/') . ':(.*)$/mi';
            if (preg_match($pattern, $fileData, $matches) === 1) {
                $data[$key] = trim((string) ($matches[1] ?? ''));
            }
        }

        return $data;
    }
}

if (!function_exists('register_activation_hook')) {
    function register_activation_hook(string $file, callable $callback): void
    {
        // no-op stub for non-WordPress environments (tests, static analysis)
    }
}

if (!function_exists('register_deactivation_hook')) {
    function register_deactivation_hook(string $file, callable $callback): void
    {
        // no-op stub for non-WordPress environments
    }
}

if (!function_exists('register_uninstall_hook')) {
    function register_uninstall_hook(string $file, callable $callback): void
    {
        // no-op stub for non-WordPress environments
    }
}

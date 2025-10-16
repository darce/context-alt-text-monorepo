<?php

declare(strict_types=1);

if (!function_exists('plugin_dir_path')) {
    function plugin_dir_path(string $file): string
    {
        return rtrim(dirname($file), '/\\') . '/';
    }
}

if (!class_exists('WP_Term')) {
    class WP_Term
    {
        /**
         * @var int
         */
        public $term_id = 0;

        /**
         * @var string
         */
        public $slug = '';

        /**
         * @var string
         */
        public $name = '';

        /**
         * @var string
         */
        public $taxonomy = '';
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

if (!function_exists('absint')) {
    function absint($maybeint): int
    {
        return abs((int) $maybeint);
    }
}

if (!function_exists('is_wp_error')) {
    function is_wp_error($thing): bool
    {
        return false;
    }
}

if (!function_exists('add_filter')) {
    function add_filter(string $tag, callable $callback, int $priority = 10, int $acceptedArgs = 1): void
    {
        unset($tag, $callback, $priority, $acceptedArgs);
    }
}

if (!function_exists('remove_filter')) {
    function remove_filter(string $tag, callable $callback, int $priority = 10): void
    {
        unset($tag, $callback, $priority);
    }
}

if (!function_exists('taxonomy_exists')) {
    function taxonomy_exists(string $taxonomy): bool
    {
        return false;
    }
}

if (!function_exists('register_taxonomy')) {
    function register_taxonomy(string $taxonomy, $objectType, array $args = []): void
    {
        unset($taxonomy, $objectType, $args);
    }
}

if (!function_exists('register_taxonomy_for_object_type')) {
    function register_taxonomy_for_object_type(string $taxonomy, string $objectType): bool
    {
        unset($taxonomy, $objectType);

        return true;
    }
}

if (!function_exists('term_exists')) {
    function term_exists($term, $taxonomy = '', $parent = null)
    {
        unset($term, $taxonomy, $parent);

        return 0;
    }
}

if (!function_exists('get_terms')) {
    /**
     * @param array<string,mixed> $args
     * @return array<int,object>
     */
    function get_terms(array $args)
    {
        unset($args);

        return [];
    }
}

if (!function_exists('get_objects_in_term')) {
    /**
     * @return array<int,int>
     */
    function get_objects_in_term(int $termId, string $taxonomy): array
    {
        unset($termId, $taxonomy);

        return [];
    }
}

if (!function_exists('wp_set_object_terms')) {
    function wp_set_object_terms(int $objectId, $terms, string $taxonomy, bool $append = false)
    {
        unset($objectId, $terms, $taxonomy, $append);

        return [];
    }
}

if (!function_exists('wp_remove_object_terms')) {
    function wp_remove_object_terms(int $objectId, $terms, string $taxonomy)
    {
        unset($objectId, $terms, $taxonomy);

        return true;
    }
}

if (!function_exists('wp_insert_term')) {
    /**
     * @param array<string,mixed> $args
     * @return array<string,int>
     */
    function wp_insert_term(string $term, string $taxonomy, array $args = []): array
    {
        unset($term, $taxonomy, $args);

        return ['term_id' => 0, 'term_taxonomy_id' => 0];
    }
}

if (!function_exists('wp_update_term')) {
    /**
     * @param array<string,mixed> $args
     * @return array<string,int>
     */
    function wp_update_term(int $termId, string $taxonomy, array $args = []): array
    {
        unset($termId, $taxonomy, $args);

        return ['term_id' => 0, 'term_taxonomy_id' => 0];
    }
}

if (!function_exists('wp_delete_term')) {
    function wp_delete_term(int $termId, string $taxonomy)
    {
        unset($termId, $taxonomy);

        return true;
    }
}

if (!function_exists('get_post_type')) {
    function get_post_type(int $postId)
    {
        unset($postId);

        return false;
    }
}

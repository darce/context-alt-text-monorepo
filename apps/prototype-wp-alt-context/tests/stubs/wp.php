<?php

declare(strict_types=1);

if (!class_exists('WP_Error')) {
    class WP_Error
    {
        /** @var string */
        private $code;
        /** @var string */
        private $message;
        /** @var mixed */
        private $data;

        public function __construct(string $code = '', string $message = '', $data = null)
        {
            $this->code = $code;
            $this->message = $message;
            $this->data = $data;
        }

        public function get_error_message(): string
        {
            return $this->message;
        }

        public function get_error_code(): string
        {
            return $this->code;
        }

        /**
         * @return mixed
         */
        public function get_error_data()
        {
            return $this->data;
        }

        /**
         * WordPress callers sometimes use get_data() on WP_Error interchangeably
         * with get_error_data(); keep the stub compatible with both call sites.
         *
         * @return mixed
         */
        public function get_data()
        {
            return $this->data;
        }
    }
}

if (!class_exists('WP_REST_Request')) {
    class WP_REST_Request implements \ArrayAccess
    {
        /** @var string */
        private $method;
        /** @var string */
        private $route;
        /** @var array<string,mixed> */
        private $params;
        /** @var array<string,mixed> */
        private $bodyParams;

        /**
         * @param string|array<string,mixed> $method HTTP method or params array (backward compatible)
         * @param string $route REST route
         * @param array<string,mixed> $params Request parameters
         */
        public function __construct($method = 'GET', string $route = '', array $params = [])
        {
            // Backward compatibility: if $method is array, treat as params
            if (is_array($method)) {
                $this->method = 'GET';
                $this->route = '';
                $this->params = $method;
                $this->bodyParams = [];
            } else {
                $this->method = $method;
                $this->route = $route;
                $this->params = $params;
                $this->bodyParams = [];
            }
        }

        public function get_param(string $key)
        {
            // Check body params first, then URL params (matches WordPress behavior)
            return $this->bodyParams[$key] ?? $this->params[$key] ?? null;
        }

        /**
         * @return array<string,mixed>
         */
        public function get_params(): array
        {
            return array_merge($this->params, $this->bodyParams);
        }

        /**
         * @return array<string,mixed>
         */
        public function get_body_params(): array
        {
            return $this->bodyParams;
        }

        /**
         * @return array<string,mixed>|null
         */
        public function get_json_params(): ?array
        {
            return $this->bodyParams ?: null;
        }

        /**
         * @param array<string,mixed> $params
         */
        public function set_body_params(array $params): void
        {
            $this->bodyParams = $params;
        }

        public function set_param(string $key, $value): self
        {
            $this->params[$key] = $value;

            return $this;
        }

        public function get_method(): string
        {
            return $this->method;
        }

        public function get_route(): string
        {
            return $this->route;
        }

        public function offsetExists(mixed $offset): bool
        {
            return array_key_exists($offset, $this->params);
        }

        public function offsetGet(mixed $offset): mixed
        {
            return $this->params[$offset] ?? null;
        }

        public function offsetSet(mixed $offset, mixed $value): void
        {
            if ($offset === null) {
                return;
            }

            $this->params[$offset] = $value;
        }

        public function offsetUnset(mixed $offset): void
        {
            unset($this->params[$offset]);
        }
    }
}

if (!function_exists('plugins_url')) {
    function plugins_url(string $path = '', string $plugin = ''): string
    {
        $base = 'http://example.test/wp-content/plugins';

        if ($plugin !== '' && str_contains($plugin, '/')) {
            $base .= '/' . trim(dirname($plugin), '/');
        }

        if ($path === '') {
            return $base;
        }

        return $base . '/' . ltrim($path, '/');
    }
}

if (!class_exists('WP_REST_Response')) {
    class WP_REST_Response
    {
        /** @var mixed */
        private $data;
        /** @var int */
        private $status;
        /** @var array<string,string> */
        private $headers = [];

        /**
         * @param mixed $data Response data.
         * @param int $status HTTP status code.
         * @param array<string,string> $headers HTTP headers.
         */
        public function __construct($data = null, int $status = 200, array $headers = [])
        {
            $this->data = $data;
            $this->status = $status;
            $this->headers = $headers;
        }

        /**
         * @return mixed
         */
        public function get_data()
        {
            return $this->data;
        }

        public function set_data($data): void
        {
            $this->data = $data;
        }

        public function get_status(): int
        {
            return $this->status;
        }

        public function set_status(int $status): void
        {
            $this->status = $status;
        }

        /**
         * @return array<string,string>
         */
        public function get_headers(): array
        {
            return $this->headers;
        }

        public function header(string $key, string $value, bool $replace = true): void
        {
            if ($replace || !isset($this->headers[$key])) {
                $this->headers[$key] = $value;
            }
        }
    }
}

if (!class_exists('WP_CLI_Command')) {
    class WP_CLI_Command {}
}

if (!class_exists('CaseInsensitiveDictionary')) {
    class CaseInsensitiveDictionary implements \ArrayAccess, \IteratorAggregate
    {
        /** @var array<string,mixed> */
        private array $items;

        /**
         * @param array<string,mixed> $items
         */
        public function __construct(array $items = [])
        {
            $this->items = [];
            foreach ($items as $key => $value) {
                $this->items[strtolower((string) $key)] = $value;
            }
        }

        public function offsetExists(mixed $offset): bool
        {
            return isset($this->items[strtolower((string) $offset)]);
        }

        public function offsetGet(mixed $offset): mixed
        {
            return $this->items[strtolower((string) $offset)] ?? null;
        }

        public function offsetSet(mixed $offset, mixed $value): void
        {
            if ($offset === null) {
                return;
            }

            $this->items[strtolower((string) $offset)] = $value;
        }

        public function offsetUnset(mixed $offset): void
        {
            unset($this->items[strtolower((string) $offset)]);
        }

        public function getIterator(): \Traversable
        {
            return new \ArrayIterator($this->items);
        }
    }
}

if (!class_exists('WP_CLI')) {
    class WP_CLI
    {
        /** @var array<string,mixed> */
        public static $commands = [];

        /** @var array<string,array<int,string>> */
        public static $messages = [
            'log' => [],
            'success' => [],
            'warning' => [],
            'error' => [],
        ];

        public static function add_command($name, $callable): void
        {
            self::$commands[$name] = $callable;
        }

        public static function log($message): void
        {
            self::$messages['log'][] = (string) $message;
        }

        public static function success($message): void
        {
            self::$messages['success'][] = (string) $message;
        }

        public static function warning($message): void
        {
            self::$messages['warning'][] = (string) $message;
        }

        public static function error($message): void
        {
            self::$messages['error'][] = (string) $message;
            throw new RuntimeException((string) $message);
        }

        public static function reset_cli_messages(): void
        {
            self::$messages = [
                'log' => [],
                'success' => [],
                'warning' => [],
                'error' => [],
            ];
        }
    }
}

if (!function_exists('absint')) {
    function absint($value): int
    {
        return abs((int) $value);
    }
}

if (!function_exists('add_action')) {
    function add_action($hook, $callback, $priority = 10, $accepted_args = 1): bool
    {
        if (!isset($GLOBALS['__ac_actions'][$hook])) {
            $GLOBALS['__ac_actions'][$hook] = [];
        }

        $GLOBALS['__ac_actions'][$hook][$priority][] = [
            'callback' => $callback,
            'accepted_args' => $accepted_args,
        ];

        return true;
    }
}

if (!function_exists('add_filter')) {
    function add_filter($hook, $callback, $priority = 10, $accepted_args = 1): bool
    {
        if (!isset($GLOBALS['__ac_filters'][$hook])) {
            $GLOBALS['__ac_filters'][$hook] = [];
        }

        $GLOBALS['__ac_filters'][$hook][$priority][] = [
            'callback' => $callback,
            'accepted_args' => $accepted_args,
        ];

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

if (!function_exists('wp_verify_nonce')) {
    function wp_verify_nonce($nonce, $action): bool
    {
        if (!is_string($nonce)) {
            return false;
        }

        return $nonce === 'nonce-' . $action;
    }
}

if (!function_exists('wp_create_nonce')) {
    function wp_create_nonce(string $action): string
    {
        return 'nonce-' . $action;
    }
}

if (!function_exists('rest_url')) {
    function rest_url(string $path = ''): string
    {
        return 'http://example.test/wp-json/' . ltrim($path, '/');
    }
}

if (!function_exists('wp_send_json_success')) {
    function wp_send_json_success($data = null, int $status_code = 200)
    {
        $response = [
            'success' => true,
            'data' => $data,
            'status' => $status_code,
        ];

        $GLOBALS['__ac_json_response'] = $response;

        return $response;
    }
}

if (!function_exists('wp_send_json_error')) {
    function wp_send_json_error($data = null, int $status_code = 400)
    {
        $response = [
            'success' => false,
            'data' => $data,
            'status' => $status_code,
        ];

        $GLOBALS['__ac_json_response'] = $response;

        return $response;
    }
}

if (!function_exists('register_rest_route')) {
    function register_rest_route($namespace, $route, $args = [], $override = false): bool
    {
        $GLOBALS['__ac_rest_routes'][] = [
            'namespace' => $namespace,
            'route' => $route,
            'args' => $args,
            'override' => $override,
        ];

        return true;
    }
}

if (!function_exists('rest_ensure_response')) {
    function rest_ensure_response($value)
    {
        if ($value instanceof WP_REST_Response || $value instanceof WP_Error) {
            return $value;
        }

        return new WP_REST_Response($value);
    }
}

if (!function_exists('esc_url')) {
    function esc_url($value)
    {
        return (string) $value;
    }
}

if (!function_exists('wp_upload_dir')) {
    /**
     * @return array<string,mixed>
     */
    function wp_upload_dir($time = null, $create_dir = true, $refresh_cache = true)
    {
        $base = sys_get_temp_dir() . '/ac-test-uploads';

        if (!is_dir($base)) {
            mkdir($base, 0777, true);
        }

        return [
            'path' => $base,
            'url' => 'http://example.test/uploads',
            'subdir' => '',
            'basedir' => $base,
            'baseurl' => 'http://example.test/uploads',
            'error' => false,
        ];
    }
}

if (!function_exists('wp_mkdir_p')) {
    function wp_mkdir_p($target)
    {
        if (is_dir($target)) {
            return true;
        }

        return mkdir($target, 0777, true);
    }
}

if (!function_exists('wp_get_attachment_metadata')) {
    /**
     * @return array<string,mixed>|false
     */
    function wp_get_attachment_metadata($attachmentId, $unfiltered = false)
    {
        return $GLOBALS['__ac_attachment_metadata'][$attachmentId] ?? false;
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

if (!function_exists('current_user_can')) {
    function current_user_can($capability, ...$args): bool
    {
        if (!isset($GLOBALS['__ac_current_user_capabilities'])) {
            $GLOBALS['__ac_current_user_capabilities'] = [];
        }

        $value = $GLOBALS['__ac_current_user_capabilities'][$capability] ?? null;

        if (is_callable($value)) {
            return (bool) $value(...$args);
        }

        if (is_array($value)) {
            $key = $args[0] ?? null;

            if ($key !== null) {
                $key = (string) $key;

                if (array_key_exists($key, $value)) {
                    return (bool) $value[$key];
                }
            }

            if (array_key_exists('default', $value)) {
                return (bool) $value['default'];
            }
        }

        if ($value !== null) {
            return (bool) $value;
        }

        return true;
    }
}

if (!function_exists('get_current_user_id')) {
    function get_current_user_id(): int
    {
        return isset($GLOBALS['__ac_current_user_id']) ? (int) $GLOBALS['__ac_current_user_id'] : 1;
    }
}

if (!function_exists('get_post')) {
    function get_post($postId)
    {
        return $GLOBALS['__ac_posts'][$postId] ?? false;
    }
}

if (!function_exists('get_posts')) {
    /**
     * @return array<int,mixed>
     */
    function get_posts($args = [])
    {
        $results = $GLOBALS['__ac_get_posts_results'] ?? [];
        if (!is_array($results)) {
            return [];
        }

        $limit = $args['posts_per_page'] ?? -1;
        if (is_numeric($limit) && (int) $limit >= 0) {
            return array_slice($results, 0, (int) $limit);
        }

        return $results;
    }
}

if (!function_exists('get_post_mime_type')) {
    function get_post_mime_type($postId)
    {
        return $GLOBALS['__ac_attachment_mimes'][$postId] ?? false;
    }
}

if (!function_exists('get_post_modified_time')) {
    function get_post_modified_time($format = 'U', $gmt = false, $post = null, $translate = false)
    {
        $postId = is_scalar($post) ? (int) $post : 0;
        return $GLOBALS['__ac_post_modified_time'][$postId] ?? null;
    }
}

if (!function_exists('wp_get_attachment_url')) {
    function wp_get_attachment_url($attachmentId)
    {
        return $GLOBALS['__ac_attachment_urls'][$attachmentId] ?? false;
    }
}

if (!function_exists('get_post_meta')) {
    function get_post_meta($postId, $key = '', $single = false)
    {
        if (!isset($GLOBALS['__ac_post_meta'][$postId])) {
            return $single ? '' : [];
        }

        if ($key === '' || $key === null) {
            return $GLOBALS['__ac_post_meta'][$postId];
        }

        if (!array_key_exists($key, $GLOBALS['__ac_post_meta'][$postId])) {
            return $single ? '' : [];
        }

        $value = $GLOBALS['__ac_post_meta'][$postId][$key];

        if ($single) {
            return $value;
        }

        return [$value];
    }
}

if (!function_exists('update_post_meta')) {
    function update_post_meta($postId, $metaKey, $metaValue)
    {
        if (!isset($GLOBALS['__ac_post_meta'])) {
            $GLOBALS['__ac_post_meta'] = [];
        }

        if (!isset($GLOBALS['__ac_post_meta'][$postId])) {
            $GLOBALS['__ac_post_meta'][$postId] = [];
        }

        $GLOBALS['__ac_post_meta'][$postId][$metaKey] = $metaValue;

        return true;
    }
}

if (!function_exists('delete_post_meta')) {
    function delete_post_meta($postId, $metaKey)
    {
        if (isset($GLOBALS['__ac_post_meta'][$postId][$metaKey])) {
            unset($GLOBALS['__ac_post_meta'][$postId][$metaKey]);
        }

        return true;
    }
}

if (!function_exists('sanitize_title')) {
    function sanitize_title($title)
    {
        $value = strtolower((string) $title);
        $value = preg_replace('/[^a-z0-9]+/i', '-', $value);
        return trim((string) $value, '-');
    }
}

if (!function_exists('sanitize_text_field')) {
    function sanitize_text_field($value)
    {
        $value = (string) $value;

        return trim(strip_tags($value));
    }
}

if (!function_exists('sanitize_key')) {
    function sanitize_key($key)
    {
        $key = strtolower((string) $key);
        return preg_replace('/[^a-z0-9_\-]/', '', $key);
    }
}

if (!function_exists('wp_unslash')) {
    function wp_unslash($value)
    {
        if (is_array($value)) {
            return array_map('wp_unslash', $value);
        }

        return stripslashes((string) $value);
    }
}

if (!function_exists('rest_sanitize_boolean')) {
    function rest_sanitize_boolean($value): bool
    {
        if (is_bool($value)) {
            return $value;
        }

        if (is_numeric($value)) {
            return (int) $value === 1;
        }

        $normalized = strtolower(trim((string) $value));
        return in_array($normalized, ['1', 'true', 'yes', 'on'], true);
    }
}

if (!function_exists('term_exists')) {
    function term_exists($term, $taxonomy)
    {
        if (!isset($GLOBALS['__ac_terms'][$taxonomy])) {
            return 0;
        }

        $slugMap = $GLOBALS['__ac_terms'][$taxonomy]['by_slug'] ?? [];

        if (is_numeric($term)) {
            $termId = (int) $term;
            if (isset($GLOBALS['__ac_terms'][$taxonomy]['by_id'][$termId])) {
                return ['term_id' => $termId, 'term_taxonomy_id' => $termId];
            }

            return 0;
        }

        $slug = (string) $term;

        if (isset($slugMap[$slug])) {
            $termId = $slugMap[$slug];
            return ['term_id' => $termId, 'term_taxonomy_id' => $termId];
        }

        return 0;
    }
}

if (!function_exists('get_term_by')) {
    /**
     * @param string $field Either 'slug', 'name', 'id', or 'term_taxonomy_id'.
     * @param string|int $value Search term.
     * @param string $taxonomy Taxonomy name.
     * @return object|false Term object on success, false if not found.
     */
    function get_term_by($field, $value, $taxonomy)
    {
        if (!isset($GLOBALS['__ac_terms'][$taxonomy])) {
            return false;
        }

        if ($field === 'slug') {
            $slug = (string) $value;
            $slugMap = $GLOBALS['__ac_terms'][$taxonomy]['by_slug'] ?? [];

            if (!isset($slugMap[$slug])) {
                return false;
            }

            $termId = $slugMap[$slug];
            $termData = $GLOBALS['__ac_terms'][$taxonomy]['by_id'][$termId] ?? null;

            if (!$termData) {
                return false;
            }

            // Count how many objects have this term assigned
            $count = 0;
            if (isset($GLOBALS['__ac_object_terms'][$taxonomy])) {
                foreach ($GLOBALS['__ac_object_terms'][$taxonomy] as $objectTerms) {
                    if (in_array($termId, $objectTerms, true)) {
                        $count++;
                    }
                }
            }

            return (object) array_merge($termData, ['count' => $count]);
        }

        if ($field === 'id' || $field === 'term_id') {
            $termId = (int) $value;
            $termData = $GLOBALS['__ac_terms'][$taxonomy]['by_id'][$termId] ?? null;

            if (!$termData) {
                return false;
            }

            // Count how many objects have this term assigned
            $count = 0;
            if (isset($GLOBALS['__ac_object_terms'][$taxonomy])) {
                foreach ($GLOBALS['__ac_object_terms'][$taxonomy] as $objectTerms) {
                    if (in_array($termId, $objectTerms, true)) {
                        $count++;
                    }
                }
            }

            return (object) array_merge($termData, ['count' => $count]);
        }

        return false;
    }
}

if (!function_exists('wp_insert_term')) {
    function wp_insert_term($term, $taxonomy, $args = [])
    {
        if (!isset($GLOBALS['__ac_terms'][$taxonomy])) {
            $GLOBALS['__ac_terms'][$taxonomy] = [
                'next_id' => 1,
                'by_id' => [],
                'by_slug' => [],
            ];
        }

        $slug = isset($args['slug']) ? (string) $args['slug'] : sanitize_title($term);

        if ($slug === '') {
            $slug = sanitize_title($term . '-' . $GLOBALS['__ac_terms'][$taxonomy]['next_id']);
        }

        if (isset($GLOBALS['__ac_terms'][$taxonomy]['by_slug'][$slug])) {
            $existing = $GLOBALS['__ac_terms'][$taxonomy]['by_slug'][$slug];

            return [
                'term_id' => $existing,
                'term_taxonomy_id' => $existing,
            ];
        }

        $termId = $GLOBALS['__ac_terms'][$taxonomy]['next_id']++;

        $GLOBALS['__ac_terms'][$taxonomy]['by_id'][$termId] = [
            'term_id' => $termId,
            'term_taxonomy_id' => $termId,
            'name' => (string) $term,
            'slug' => $slug,
            'taxonomy' => $taxonomy,
        ];

        $GLOBALS['__ac_terms'][$taxonomy]['by_slug'][$slug] = $termId;

        return [
            'term_id' => $termId,
            'term_taxonomy_id' => $termId,
        ];
    }
}

if (!function_exists('wp_get_object_terms')) {
    function wp_get_object_terms($object_id, $taxonomy, $args = [])
    {
        $objectId = (int) $object_id;

        $termIds = $GLOBALS['__ac_object_terms'][$taxonomy][$objectId] ?? [];
        $terms = [];

        foreach ($termIds as $termId) {
            if (!isset($GLOBALS['__ac_terms'][$taxonomy]['by_id'][$termId])) {
                continue;
            }

            $data = $GLOBALS['__ac_terms'][$taxonomy]['by_id'][$termId];
            $terms[] = (object) $data;
        }

        return $terms;
    }
}

if (!function_exists('wp_set_post_terms')) {
    function wp_set_post_terms($object_id, $terms, $taxonomy, $append = false)
    {
        return wp_set_object_terms($object_id, $terms, $taxonomy, $append);
    }
}

if (!function_exists('wp_set_object_terms')) {
    function wp_set_object_terms($object_id, $terms, $taxonomy, $append = false)
    {
        $objectId = (int) $object_id;
        $termIds = is_array($terms) ? array_map('intval', $terms) : [(int) $terms];
        $termIds = array_values(array_filter($termIds, static fn($id) => $id > 0));

        if (!isset($GLOBALS['__ac_object_terms'][$taxonomy])) {
            $GLOBALS['__ac_object_terms'][$taxonomy] = [];
        }

        if ($append && isset($GLOBALS['__ac_object_terms'][$taxonomy][$objectId])) {
            $existing = $GLOBALS['__ac_object_terms'][$taxonomy][$objectId];
            $termIds = array_values(array_unique(array_merge($existing, $termIds)));
        }

        $GLOBALS['__ac_object_terms'][$taxonomy][$objectId] = $termIds;

        return $termIds;
    }
}

if (!function_exists('wp_generate_uuid4')) {
    function wp_generate_uuid4(): string
    {
        if (!isset($GLOBALS['__ac_uuid_counter'])) {
            $GLOBALS['__ac_uuid_counter'] = 0;
        }

        $GLOBALS['__ac_uuid_counter']++;

        return 'uuid-' . $GLOBALS['__ac_uuid_counter'];
    }
}

if (!function_exists('wp_upload_bits')) {
    function wp_upload_bits($name, $deprecated, $bits)
    {
        $directory = sys_get_temp_dir();
        $unique = uniqid('ac_upload_', true);
        $path = $directory . '/' . $unique . '_' . $name;

        file_put_contents($path, $bits);

        return [
            'file' => $path,
            'url' => 'http://example.test/uploads/' . $name,
            'error' => false,
        ];
    }
}

if (!function_exists('wp_insert_attachment')) {
    function wp_insert_attachment($attachment, $filename = '', $parent = 0)
    {
        if (!isset($GLOBALS['__ac_attachments'])) {
            $GLOBALS['__ac_attachments'] = [];
        }

        $id = isset($attachment['ID']) ? (int) $attachment['ID'] : (count($GLOBALS['__ac_attachments']) + 1);
        $GLOBALS['__ac_attachments'][$id] = array_merge($attachment, [
            'ID' => $id,
            'file' => $filename,
            'parent' => $parent,
        ]);

        return $id;
    }
}

if (!function_exists('get_transient')) {
    function get_transient($transient)
    {
        return $GLOBALS['__ac_transients'][$transient] ?? false;
    }
}

if (!function_exists('set_transient')) {
    function set_transient($transient, $value, $expiration = 0): bool
    {
        if (!isset($GLOBALS['__ac_transients'])) {
            $GLOBALS['__ac_transients'] = [];
        }

        $GLOBALS['__ac_transients'][$transient] = $value;

        return true;
    }
}

if (!function_exists('delete_transient')) {
    function delete_transient($transient): bool
    {
        if (!isset($GLOBALS['__ac_transients'])) {
            return true;
        }

        unset($GLOBALS['__ac_transients'][$transient]);
        return true;
    }
}

if (!function_exists('wp_next_scheduled')) {
    function wp_next_scheduled($hook, $args = [])
    {
        $key = $hook . '::' . md5(serialize($args));

        return $GLOBALS['__ac_scheduled'][$key]['timestamp'] ?? false;
    }
}

if (!function_exists('wp_schedule_single_event')) {
    function wp_schedule_single_event($timestamp, $hook, $args = []): void
    {
        $key = $hook . '::' . md5(serialize($args));
        $GLOBALS['__ac_scheduled'][$key] = [
            'timestamp' => $timestamp,
            'args' => $args,
        ];
    }
}

if (!function_exists('wp_schedule_event')) {
    function wp_schedule_event($timestamp, $recurrence, $hook, $args = []): void
    {
        $key = $hook . '::' . md5(serialize($args));
        $GLOBALS['__ac_scheduled'][$key] = [
            'timestamp' => $timestamp,
            'recurrence' => $recurrence,
            'args' => $args,
        ];
    }
}

if (!function_exists('wp_clear_scheduled_hook')) {
    function wp_clear_scheduled_hook($hook, $args = []): void
    {
        $key = $hook . '::' . md5(serialize($args));
        unset($GLOBALS['__ac_scheduled'][$key]);
    }
}

if (!function_exists('as_next_scheduled_action')) {
    function as_next_scheduled_action($hook, $args = [], $group = '')
    {
        $key = $hook . '::' . $group . '::' . md5(serialize($args));
        return $GLOBALS['__ac_action_scheduler'][$key]['timestamp'] ?? false;
    }
}

if (!function_exists('as_enqueue_async_action')) {
    function as_enqueue_async_action($hook, $args = [], $group = ''): int
    {
        $forcedResult = $GLOBALS['__ac_action_scheduler_enqueue_result'] ?? null;
        if (is_int($forcedResult)) {
            if ($forcedResult <= 0) {
                return $forcedResult;
            }
        }

        $key = $hook . '::' . $group . '::' . md5(serialize($args));
        $GLOBALS['__ac_action_scheduler'][$key] = [
            'timestamp' => time(),
            'hook' => $hook,
            'args' => $args,
            'group' => $group,
        ];

        if (is_int($forcedResult) && $forcedResult > 0) {
            return $forcedResult;
        }

        return count($GLOBALS['__ac_action_scheduler']);
    }
}

if (!function_exists('as_unschedule_all_actions')) {
    function as_unschedule_all_actions($hook, $args = [], $group = ''): void
    {
        $key = $hook . '::' . $group . '::' . md5(serialize($args));
        unset($GLOBALS['__ac_action_scheduler'][$key]);
    }
}

if (!function_exists('update_option')) {
    function update_option($key, $value)
    {
        $GLOBALS['__ac_options'][$key] = $value;
        return true;
    }
}

if (!function_exists('get_option')) {
    function get_option($key, $default = false)
    {
        return $GLOBALS['__ac_options'][$key] ?? $default;
    }
}

if (!function_exists('delete_option')) {
    function delete_option($key): void
    {
        unset($GLOBALS['__ac_options'][$key]);
    }
}

if (!function_exists('get_attached_file')) {
    function get_attached_file($attachmentId, $unfiltered = false)
    {
        return $GLOBALS['__ac_attached_file'][$attachmentId] ?? false;
    }
}

if (!function_exists('wp_get_image_editor')) {
    /**
     * @param string $path
     * @return WP_Error|object
     */
    function wp_get_image_editor($path)
    {
        // Check if test has set a mock editor
        if (isset($GLOBALS['__ac_image_editor'])) {
            return $GLOBALS['__ac_image_editor'];
        }

        // Default: return error
        return new WP_Error('file_not_found', 'Image file not found', ['path' => $path]);
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
        if (empty($GLOBALS['__ac_filters'][$hook])) {
            return $value;
        }

        ksort($GLOBALS['__ac_filters'][$hook]);

        $args = func_get_args();
        array_shift($args); // remove hook name

        foreach ($GLOBALS['__ac_filters'][$hook] as $priority => $callbacks) {
            foreach ($callbacks as $data) {
                $accepted = (int) $data['accepted_args'];
                if ($accepted <= 0) {
                    $accepted = 1;
                }

                $callArgs = array_slice($args, 0, $accepted);

                if (empty($callArgs)) {
                    $callArgs = [$value];
                } else {
                    $callArgs[0] = $value;
                }

                $value = $data['callback'](...$callArgs);
                $args[0] = $value;
            }
        }

        return $value;
    }
}

if (!function_exists('do_action')) {
    function do_action($hook, ...$args): void
    {
        if (!isset($GLOBALS['__ac_do_action_log'])) {
            $GLOBALS['__ac_do_action_log'] = [];
        }

        $GLOBALS['__ac_do_action_log'][] = [
            'hook' => (string) $hook,
            'args' => $args,
        ];

        if (empty($GLOBALS['__ac_actions'][$hook])) {
            return;
        }

        ksort($GLOBALS['__ac_actions'][$hook]);

        foreach ($GLOBALS['__ac_actions'][$hook] as $priority => $callbacks) {
            foreach ($callbacks as $data) {
                $accepted = (int) $data['accepted_args'];
                $callArgs = $accepted > 0 ? array_slice($args, 0, $accepted) : [];
                $data['callback'](...$callArgs);
            }
        }
    }
}

if (!function_exists('register_setting')) {
    function register_setting($option_group, $option_name, $args = []): bool
    {
        $GLOBALS['__ac_registered_settings'][$option_name] = [
            'group' => $option_group,
            'args' => $args,
        ];

        return true;
    }
}

if (!function_exists('add_settings_section')) {
    function add_settings_section($id, $title, $callback, $page, $args = []): bool
    {
        $GLOBALS['__ac_settings_sections'][$page][$id] = [
            'title' => $title,
            'callback' => $callback,
            'args' => $args,
        ];

        return true;
    }
}

if (!function_exists('add_settings_field')) {
    function add_settings_field($id, $title, $callback, $page, $section = 'default', $args = []): bool
    {
        $GLOBALS['__ac_settings_fields'][$page][$section][$id] = [
            'title' => $title,
            'callback' => $callback,
            'args' => $args,
        ];

        return true;
    }
}

if (!function_exists('settings_fields')) {
    function settings_fields($option_group): void
    {
        echo '<input type="hidden" name="option_page" value="' . esc_attr((string) $option_group) . '" />';
        echo '<input type="hidden" name="action" value="update" />';
    }
}

if (!function_exists('settings_errors')) {
    function settings_errors($setting = '', $sanitize = false, $hide_on_update = false)
    {
        return [];
    }
}

if (!function_exists('do_settings_sections')) {
    function do_settings_sections($page): void
    {
        if (empty($GLOBALS['__ac_settings_sections'][$page])) {
            return;
        }

        foreach ($GLOBALS['__ac_settings_sections'][$page] as $sectionId => $section) {
            if (is_callable($section['callback'])) {
                $callback = $section['callback'];
                $args = $section['args'] ?? [];
                $callback($args);
            }

            if (empty($GLOBALS['__ac_settings_fields'][$page][$sectionId])) {
                continue;
            }

            foreach ($GLOBALS['__ac_settings_fields'][$page][$sectionId] as $field) {
                if (is_callable($field['callback'])) {
                    $callback = $field['callback'];
                    $args = $field['args'] ?? [];
                    $callback($args);
                }
            }
        }
    }
}

if (!function_exists('submit_button')) {
    function submit_button($text = null): void
    {
        $label = $text !== null ? (string) $text : 'Save Changes';
        echo '<button type="submit" class="button button-primary">' . esc_html($label) . '</button>';
    }
}

if (!function_exists('number_format_i18n')) {
    function number_format_i18n($number, $decimals = 0)
    {
        return number_format((float) $number, (int) $decimals);
    }
}

if (!function_exists('wp_json_encode')) {
    function wp_json_encode($data, $options = 0, $depth = 512)
    {
        return json_encode($data, $options, $depth);
    }
}


if (!function_exists('wp_remote_post')) {
    function wp_remote_post($url, $args = [])
    {
        if (!isset($GLOBALS['__ac_http_calls'])) {
            $GLOBALS['__ac_http_calls'] = [];
        }

        $GLOBALS['__ac_http_calls'][] = [
            'url' => $url,
            'args' => $args,
            'method' => 'POST',
            'body' => $args['body'] ?? '',
        ];

        if (!empty($GLOBALS['__ac_http_queue'])) {
            return array_shift($GLOBALS['__ac_http_queue']);
        }

        return [
            'response' => [
                'code' => 200,
                'message' => 'OK',
            ],
            'body' => '',
        ];
    }
}

if (!function_exists('wp_remote_get')) {
    function wp_remote_get($url, $args = [])
    {
        if (!isset($GLOBALS['__ac_http_calls'])) {
            $GLOBALS['__ac_http_calls'] = [];
        }

        $GLOBALS['__ac_http_calls'][] = [
            'url' => $url,
            'args' => $args,
            'method' => 'GET',
            'body' => $args['body'] ?? '',
        ];

        if (!empty($GLOBALS['__ac_http_queue'])) {
            return array_shift($GLOBALS['__ac_http_queue']);
        }

        return [
            'response' => [
                'code' => 200,
                'message' => 'OK',
            ],
            'body' => '',
        ];
    }
}

if (!function_exists('wp_remote_head')) {
    function wp_remote_head($url, $args = [])
    {
        if (!isset($GLOBALS['__ac_http_calls'])) {
            $GLOBALS['__ac_http_calls'] = [];
        }

        $GLOBALS['__ac_http_calls'][] = [
            'url' => $url,
            'args' => $args,
            'method' => 'HEAD',
            'body' => '',
        ];

        if (!empty($GLOBALS['__ac_http_queue'])) {
            return array_shift($GLOBALS['__ac_http_queue']);
        }

        return [
            'response' => [
                'code' => 200,
                'message' => 'OK',
            ],
            'body' => '',
        ];
    }
}

if (!function_exists('wp_remote_request')) {
    function wp_remote_request($url, $args = [])
    {
        if (!isset($GLOBALS['__ac_http_calls'])) {
            $GLOBALS['__ac_http_calls'] = [];
        }

        $method = isset($args['method']) ? strtoupper((string) $args['method']) : 'GET';

        $GLOBALS['__ac_http_calls'][] = [
            'url' => $url,
            'args' => $args,
            'method' => $method,
            'body' => $args['body'] ?? '',
        ];

        if (!empty($GLOBALS['__ac_http_queue'])) {
            return array_shift($GLOBALS['__ac_http_queue']);
        }

        return [
            'response' => [
                'code' => 200,
                'message' => 'OK',
            ],
            'body' => '',
        ];
    }
}

if (!function_exists('current_time')) {
    function current_time($type, $gmt = 0)
    {
        $timestamp = time();
        $gmtOffset = (float) get_option('gmt_offset', 0);
        $offsetSeconds = (int) round($gmtOffset * 3600);
        $localizedTimestamp = $timestamp + $offsetSeconds;

        if ($type === 'timestamp') {
            return $gmt ? $timestamp : $localizedTimestamp;
        }

        if ($type === 'mysql') {
            return gmdate('Y-m-d H:i:s', $gmt ? $timestamp : $localizedTimestamp);
        }

        return $timestamp;
    }
}

if (!function_exists('wp_remote_retrieve_response_code')) {
    function wp_remote_retrieve_response_code($response)
    {
        if (is_array($response) && isset($response['response']['code'])) {
            return (int) $response['response']['code'];
        }

        return 0;
    }
}

if (!function_exists('wp_remote_retrieve_response_message')) {
    function wp_remote_retrieve_response_message($response)
    {
        if (is_array($response) && isset($response['response']['message'])) {
            return (string) $response['response']['message'];
        }

        return '';
    }
}

if (!function_exists('wp_remote_retrieve_body')) {
    function wp_remote_retrieve_body($response)
    {
        if (is_array($response) && array_key_exists('body', $response)) {
            return (string) $response['body'];
        }

        return '';
    }
}

if (!function_exists('wp_remote_retrieve_headers')) {
    function wp_remote_retrieve_headers($response)
    {
        if (is_array($response) && isset($response['headers']) && is_array($response['headers'])) {
            return new CaseInsensitiveDictionary($response['headers']);
        }

        return new CaseInsensitiveDictionary();
    }
}

if (!function_exists('wp_remote_retrieve_header')) {
    function wp_remote_retrieve_header($response, $header)
    {
        $headers = wp_remote_retrieve_headers($response);

        return $headers[$header] ?? '';
    }
}

if (!function_exists('is_wp_error')) {
    function is_wp_error($thing): bool
    {
        return $thing instanceof WP_Error;
    }
}

if (!function_exists('wp_enqueue_script')) {
    function wp_enqueue_script($handle, $src = '', $deps = [], $ver = false, $in_footer = false): void
    {
        $GLOBALS['__ac_scripts'][$handle] = compact('src', 'deps', 'ver', 'in_footer');
    }
}

if (!function_exists('wp_script_add_data')) {
    function wp_script_add_data($handle, $key, $value): void
    {
        if (!isset($GLOBALS['__ac_scripts'][$handle])) {
            $GLOBALS['__ac_scripts'][$handle] = [];
        }

        if (!isset($GLOBALS['__ac_scripts'][$handle]['data']) || !is_array($GLOBALS['__ac_scripts'][$handle]['data'])) {
            $GLOBALS['__ac_scripts'][$handle]['data'] = [];
        }

        $GLOBALS['__ac_scripts'][$handle]['data'][$key] = $value;
    }
}

if (!function_exists('wp_enqueue_style')) {
    function wp_enqueue_style($handle, $src = '', $deps = [], $ver = false, $media = 'all'): void
    {
        $GLOBALS['__ac_styles'][$handle] = compact('src', 'deps', 'ver', 'media');
    }
}

if (!function_exists('wp_localize_script')) {
    function wp_localize_script($handle, $object_name, $l10n): void
    {
        $GLOBALS['__ac_localized_scripts'][$handle][$object_name] = $l10n;
    }
}

if (!function_exists('wp_get_environment_type')) {
    function wp_get_environment_type(): string
    {
        return $_ENV['WP_ENVIRONMENT_TYPE'] ?? 'production';
    }
}

// WP_Query is provided by szepeviktor/phpstan-wordpress extension stubs.
// Do NOT redefine it here — the minimal stub conflicts with the real signature.

if (!defined('OBJECT')) {
    define('OBJECT', 'OBJECT');
}

if (!defined('ARRAY_A')) {
    define('ARRAY_A', 'ARRAY_A');
}

if (!defined('ARRAY_N')) {
    define('ARRAY_N', 'ARRAY_N');
}

if (!isset($GLOBALS['wpdb'])) {
    class WPDBStub
    {
        /** @var array<int,string> */
        public array $queries = [];
        /** @var array<string,mixed> */
        public array $queryResults = [];
        /** @var mixed */
        public $defaultQueryResult = true;
        public string $prefix = 'wp_';
        public string $postmeta = 'wp_postmeta';
        public string $term_relationships = 'wp_term_relationships';
        /** @var array<int,array<string,mixed>> */
        public array $mockResults = [];
        /** @var array<string,mixed>|null */
        public ?array $mockRow = null;
        /** @var mixed */
        public $mockVar = null;
        public int $insert_id = 0;
        public int $rows_affected = 0;
        /** @var mixed */
        public $defaultInsertResult = 1;
        /** @var array<string,mixed> */
        public array $insertResults = [];
        /** @var mixed */
        public $defaultUpdateResult = 1;
        /** @var array<string,mixed> */
        public array $updateResults = [];
        /** @var array<string,array<int,array<string,mixed>>> */
        public array $tableRows = [];

        public function query($sql)
        {
            $normalizedSql = trim((string) $sql);
            $this->queries[] = $normalizedSql;

            $result = $this->defaultQueryResult;
            if (array_key_exists($normalizedSql, $this->queryResults)) {
                $result = $this->queryResults[$normalizedSql];
            }

            if ($result === false || $result === null) {
                $this->rows_affected = 0;
                return $result;
            }

            if (is_int($result)) {
                $this->rows_affected = $result;
                return $result;
            }

            $this->rows_affected = preg_match('/^(UPDATE|DELETE|INSERT)\b/i', $normalizedSql) ? 1 : 0;
            return $result;
        }

        public function get_charset_collate(): string
        {
            return 'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci';
        }

        public function prepare(string $query, ...$args): string
        {
            if ($args === []) {
                return $query;
            }

            $segments = preg_split('/(%s|%d|%f|%i)/', $query, -1, PREG_SPLIT_DELIM_CAPTURE);
            if ($segments === false) {
                return $query;
            }

            $result = '';
            $argIndex = 0;

            foreach ($segments as $segment) {
                if ($segment === '%s') {
                    $value = $args[$argIndex++] ?? '';
                    $result .= "'" . addslashes((string) $value) . "'";
                    continue;
                }

                if ($segment === '%d') {
                    $value = $args[$argIndex++] ?? 0;
                    $result .= (string) (int) $value;
                    continue;
                }

                if ($segment === '%f') {
                    $value = $args[$argIndex++] ?? 0.0;
                    $result .= (string) (float) $value;
                    continue;
                }

                if ($segment === '%i') {
                    $value = $args[$argIndex++] ?? '';
                    $identifier = str_replace('`', '', (string) $value);
                    $result .= '`' . $identifier . '`';
                    continue;
                }

                $result .= $segment;
            }

            return $result;
        }

        public function esc_like(string $text): string
        {
            return addcslashes($text, '_%');
        }

        public function has_cap(string $cap): bool
        {
            return $cap === 'identifier_placeholders';
        }

        public function get_results($query, $output = OBJECT)
        {
            $normalizedSql = trim((string) $query);
            $this->queries[] = $normalizedSql;

            $results = $this->mockResults;
            if ($results === []) {
                $results = $this->resolveStoredSelectResults($normalizedSql);
            }
            if ($output === ARRAY_A) {
                $mapped = $results;
            } elseif ($output === OBJECT) {
                $mapped = array_map(static fn(array $row) => (object) $row, $results);
            } else {
                $mapped = $results;
            }

            return $mapped;
        }

        public function get_row($query, $output = OBJECT, $y = 0)
        {
            $normalizedSql = trim((string) $query);
            $this->queries[] = $normalizedSql;

            $row = $this->mockRow;
            if ($row === null) {
                $results = $this->resolveStoredSelectResults($normalizedSql);
                $row = $results[0] ?? null;
            }

            if ($row === null) {
                return null;
            }

            if ($output === ARRAY_A) {
                return $row;
            }

            if ($output === OBJECT) {
                return (object) $row;
            }

            return $row;
        }

        public function get_var($query, $x = 0, $y = 0)
        {
            $normalizedSql = trim((string) $query);
            $this->queries[] = $normalizedSql;
            
            if (array_key_exists($normalizedSql, $this->queryResults)) {
                return $this->queryResults[$normalizedSql];
            }

            $results = $this->resolveStoredSelectResults($normalizedSql);
            if ($results !== []) {
                $firstRow = $results[0];
                $firstKey = array_key_first($firstRow);
                if (is_string($firstKey) || is_int($firstKey)) {
                    return $firstRow[$firstKey];
                }
            }

            return $this->mockVar;
        }

        public function insert(string $table, array $data, $format = null)
        {
            $columns = array_keys($data);
            $values = array_map(static function ($value): string {
                if ($value === null) {
                    return 'NULL';
                }

                if (is_numeric($value)) {
                    return (string) $value;
                }

                return "'" . addslashes((string) $value) . "'";
            }, array_values($data));

            $sql = sprintf(
                'INSERT INTO %s (%s) VALUES (%s)',
                $table,
                implode(', ', $columns),
                implode(', ', $values)
            );

            $this->queries[] = $sql;

            $result = $this->defaultInsertResult;
            if (array_key_exists($sql, $this->insertResults)) {
                $result = $this->insertResults[$sql];
            }

            if ($result === false || $result === null) {
                $this->rows_affected = 0;
                return $result;
            }

            if (is_int($result)) {
                $this->rows_affected = $result;
            } else {
                $this->rows_affected = 1;
            }

            if ($this->insert_id === 0) {
                $this->insert_id = 1;
            }

            if (!isset($this->tableRows[$table])) {
                $this->tableRows[$table] = [];
            }

            $row = $data;
            if (!array_key_exists('id', $row) && preg_match('/_failures$/', $table) === 1) {
                $row['id'] = count($this->tableRows[$table]) + 1;
            }

            $this->tableRows[$table][] = $row;

            return $result;
        }

        public function update(string $table, array $data, array $where, $format = null, $whereFormat = null)
        {
            $setParts = [];
            foreach ($data as $column => $value) {
                if ($value === null) {
                    $setParts[] = sprintf("%s = NULL", $column);
                } elseif (is_numeric($value)) {
                    $setParts[] = sprintf("%s = %s", $column, (string) $value);
                } else {
                    $setParts[] = sprintf("%s = '%s'", $column, addslashes((string) $value));
                }
            }

            $whereParts = [];
            foreach ($where as $column => $value) {
                if ($value === null) {
                    $whereParts[] = sprintf("%s IS NULL", $column);
                } elseif (is_numeric($value)) {
                    $whereParts[] = sprintf("%s = %s", $column, (string) $value);
                } else {
                    $whereParts[] = sprintf("%s = '%s'", $column, addslashes((string) $value));
                }
            }

            $sql = sprintf(
                'UPDATE %s SET %s WHERE %s',
                $table,
                implode(', ', $setParts),
                implode(' AND ', $whereParts)
            );

            $this->queries[] = $sql;

            $result = $this->defaultUpdateResult;
            if (array_key_exists($sql, $this->updateResults)) {
                $result = $this->updateResults[$sql];
            }

            if ($result === false || $result === null) {
                $this->rows_affected = 0;
                return $result;
            }

            if (is_int($result)) {
                $this->rows_affected = $result;
                $this->applyUpdateToRows($table, $data, $where);
                return $result;
            }

            $this->rows_affected = 1;
            $this->applyUpdateToRows($table, $data, $where);
            return $result;
        }

        public function delete(string $table, array $where, $whereFormat = null)
        {
            $whereParts = [];
            foreach ($where as $column => $value) {
                if ($value === null) {
                    $whereParts[] = sprintf("%s IS NULL", $column);
                } elseif (is_numeric($value)) {
                    $whereParts[] = sprintf("%s = %s", $column, (string) $value);
                } else {
                    $whereParts[] = sprintf("%s = '%s'", $column, addslashes((string) $value));
                }
            }

            $sql = sprintf(
                'DELETE FROM %s WHERE %s',
                $table,
                implode(' AND ', $whereParts)
            );

            $this->queries[] = $sql;

            if (isset($this->tableRows[$table])) {
                $this->tableRows[$table] = array_values(array_filter(
                    $this->tableRows[$table],
                    fn(array $row): bool => !$this->rowMatchesWhere($row, $where)
                ));
            }

            return 1;
        }

        /** @return array<int,array<string,mixed>> */
        private function resolveStoredSelectResults(string $query): array
        {
            $parsed = $this->parseSelectQuery($query);
            if ($parsed === null) {
                return [];
            }

            $rows = $this->tableRows[$parsed['table']] ?? [];
            $rows = array_values(array_filter(
                $rows,
                fn(array $row): bool => $this->rowMatchesParsedConditions($row, $parsed['conditions'])
            ));

            if ($parsed['orderBy'] !== null) {
                usort(
                    $rows,
                    function (array $left, array $right) use ($parsed): int {
                        $column = $parsed['orderBy'];
                        $direction = $parsed['orderDirection'];
                        $leftValue = $left[$column] ?? null;
                        $rightValue = $right[$column] ?? null;
                        $comparison = $leftValue <=> $rightValue;
                        return $direction === 'DESC' ? -$comparison : $comparison;
                    }
                );
            }

            if ($parsed['limit'] !== null) {
                $rows = array_slice($rows, 0, $parsed['limit']);
            }

            if ($parsed['select'] === '*') {
                return $rows;
            }

            $columns = array_map('trim', explode(',', $parsed['select']));
            return array_map(
                static function (array $row) use ($columns): array {
                    $projected = [];
                    foreach ($columns as $column) {
                        $normalized = trim($column, " `");
                        $projected[$normalized] = $row[$normalized] ?? null;
                    }

                    return $projected;
                },
                $rows
            );
        }

        /** @return array{select:string,table:string,conditions:array<int,array<string,mixed>>,orderBy:?string,orderDirection:string,limit:?int}|null */
        private function parseSelectQuery(string $query): ?array
        {
            $matches = [];
            if (preg_match('/^SELECT\s+(?P<select>.+?)\s+FROM\s+`?(?P<table>[A-Za-z0-9_]+)`?(?:\s+WHERE\s+(?P<where>.+?))?(?:\s+ORDER BY\s+`?(?P<order>[A-Za-z0-9_]+)`?\s+(?P<direction>ASC|DESC))?(?:\s+LIMIT\s+(?P<limit>\d+))?$/i', $query, $matches) !== 1) {
                return null;
            }

            $conditions = [];
            if (isset($matches['where']) && $matches['where'] !== '') {
                $parts = preg_split('/\s+AND\s+/i', trim($matches['where']));
                if (is_array($parts)) {
                    foreach ($parts as $part) {
                        $condition = trim($part);
                        if (preg_match('/^`?(?P<column>[A-Za-z0-9_]+)`?\s+IN\s*\((?P<values>.+)\)$/i', $condition, $conditionMatches) === 1) {
                            $values = array_map(
                                static fn(string $value): string => trim($value, " '\t\n\r\0\x0B"),
                                explode(',', $conditionMatches['values'])
                            );
                            $values = array_values(array_filter($values, static fn(string $value): bool => $value !== ''));
                            $conditions[] = ['type' => 'in', 'column' => $conditionMatches['column'], 'values' => $values];
                            continue;
                        }
                        if (preg_match('/^`?(?P<column>[A-Za-z0-9_]+)`?\s*=\s*\'(?P<value>.*)\'$/', $condition, $conditionMatches) === 1) {
                            $conditions[] = ['type' => 'eq', 'column' => $conditionMatches['column'], 'value' => stripslashes($conditionMatches['value'])];
                            continue;
                        }
                        if (preg_match('/^`?(?P<column>[A-Za-z0-9_]+)`?\s*=\s*(?P<value>\d+)$/', $condition, $conditionMatches) === 1) {
                            $conditions[] = ['type' => 'eq', 'column' => $conditionMatches['column'], 'value' => $conditionMatches['value']];
                            continue;
                        }
                        if (preg_match('/^`?(?P<column>[A-Za-z0-9_]+)`?\s+LIKE\s+\'(?P<value>.*)\'$/', $condition, $conditionMatches) === 1) {
                            $conditions[] = ['type' => 'like', 'column' => $conditionMatches['column'], 'value' => stripslashes($conditionMatches['value'])];
                            continue;
                        }
                        if (preg_match('/^`?(?P<column>[A-Za-z0-9_]+)`?\s+IS\s+NULL$/i', $condition, $conditionMatches) === 1) {
                            $conditions[] = ['type' => 'null', 'column' => $conditionMatches['column'], 'value' => ''];
                        }
                    }
                }
            }

            return [
                'select' => trim($matches['select']),
                'table' => $matches['table'],
                'conditions' => $conditions,
                'orderBy' => isset($matches['order']) && $matches['order'] !== '' ? $matches['order'] : null,
                'orderDirection' => strtoupper($matches['direction'] ?? 'ASC'),
                'limit' => isset($matches['limit']) && $matches['limit'] !== '' ? (int) $matches['limit'] : null,
            ];
        }

        /** @param array<int,array<string,mixed>> $conditions */
        private function rowMatchesParsedConditions(array $row, array $conditions): bool
        {
            foreach ($conditions as $condition) {
                $column = $condition['column'];
                $value = $row[$column] ?? null;
                if ($condition['type'] === 'in') {
                    $values = $condition['values'] ?? [];
                    if (!is_array($values) || !in_array((string) $value, array_map('strval', $values), true)) {
                        return false;
                    }
                }
                if ($condition['type'] === 'eq' && (string) $value !== $condition['value']) {
                    return false;
                }
                if ($condition['type'] === 'like') {
                    $needle = str_replace('%', '', $condition['value']);
                    if ($needle !== '' && strpos((string) $value, $needle) === false) {
                        return false;
                    }
                }
                if ($condition['type'] === 'null' && $value !== null) {
                    return false;
                }
            }

            return true;
        }

        private function applyUpdateToRows(string $table, array $data, array $where): void
        {
            if (!isset($this->tableRows[$table])) {
                return;
            }

            foreach ($this->tableRows[$table] as $index => $row) {
                if (!$this->rowMatchesWhere($row, $where)) {
                    continue;
                }

                $this->tableRows[$table][$index] = array_merge($row, $data);
            }
        }

        private function rowMatchesWhere(array $row, array $where): bool
        {
            foreach ($where as $column => $value) {
                if (($row[$column] ?? null) != $value) {
                    return false;
                }
            }

            return true;
        }

        public function reset(): void
        {
            $this->queries = [];
            $this->queryResults = [];
            $this->defaultQueryResult = true;
            $this->mockResults = [];
            $this->mockRow = null;
            $this->mockVar = null;
            $this->insert_id = 0;
            $this->rows_affected = 0;
            $this->defaultInsertResult = 1;
            $this->insertResults = [];
            $this->defaultUpdateResult = 1;
            $this->updateResults = [];
            $this->tableRows = [];
        }
    }

    $GLOBALS['wpdb'] = new WPDBStub();
}

if (!function_exists('dbDelta')) {
    /**
     * Record dbDelta invocations for lifecycle schema tests.
     *
     * @param string|array<int,string> $queries SQL string or list of SQL strings.
     * @return array<int,string>
     */
    function dbDelta($queries = '')
    {
        if (!isset($GLOBALS['__ac_dbdelta_queries']) || !is_array($GLOBALS['__ac_dbdelta_queries'])) {
            $GLOBALS['__ac_dbdelta_queries'] = [];
        }

        $sqlList = is_array($queries) ? $queries : [$queries];
        $executed = [];

        foreach ($sqlList as $sql) {
            if (!is_string($sql)) {
                continue;
            }

            $normalized = trim($sql);
            if ($normalized === '') {
                continue;
            }

            $GLOBALS['__ac_dbdelta_queries'][] = $normalized;
            $executed[] = $normalized;
        }

        return $executed;
    }
}

if (!function_exists('nocache_headers')) {
    function nocache_headers(): void
    {
        // No-op in tests.
    }
}

if (!function_exists('connection_aborted')) {
    function connection_aborted(): bool
    {
        if (!isset($GLOBALS['__ac_connection_aborted'])) {
            return false;
        }

        if (is_bool($GLOBALS['__ac_connection_aborted'])) {
            return $GLOBALS['__ac_connection_aborted'];
        }

        if (is_int($GLOBALS['__ac_connection_aborted'])) {
            $GLOBALS['__ac_connection_aborted_call_count'] = ($GLOBALS['__ac_connection_aborted_call_count'] ?? 0) + 1;

            return $GLOBALS['__ac_connection_aborted_call_count'] >= $GLOBALS['__ac_connection_aborted'];
        }

        return false;
    }
}

if (!function_exists('flush_rewrite_rules')) {
    /**
     * Stub for flush_rewrite_rules.
     *
     * @param bool $hard Whether to flush hard rules (htaccess).
     */
    function flush_rewrite_rules($hard = true): void
    {
        // No-op in tests
    }
}

if (!function_exists('get_site_url')) {
    /**
     * Stub for get_site_url.
     *
     * @param int|null $blog_id Site ID. Null for current site.
     * @param string $path Path to append.
     * @param string|null $scheme URL scheme.
     * @return string Site URL.
     */
    function get_site_url($blog_id = null, string $path = '', $scheme = null): string
    {
        $base = $GLOBALS['__ac_site_url'] ?? 'http://example.com';

        return $base . ($path ? '/' . ltrim($path, '/') : '');
    }
}

if (!function_exists('wp_is_uuid')) {
    function wp_is_uuid($uuid): bool
    {
        if (!is_string($uuid)) {
            return false;
        }

        $uuid = strtolower($uuid);

        return (bool) preg_match(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/',
            $uuid
        );
    }
}

if (!function_exists('untrailingslashit')) {
    /**
     * Remove trailing slash from string.
     */
    function untrailingslashit(string $value): string
    {
        return rtrim($value, '/\\');
    }
}

if (!function_exists('esc_url_raw')) {
    /**
     * Sanitize a URL for database storage or redirect.
     */
    function esc_url_raw(string $url, $protocols = null): string
    {
        return $url; // Minimal stub - just pass through
    }
}

if (!function_exists('add_query_arg')) {
    /**
     * Add query args to a URL.
     */
    function add_query_arg($args, string $url = ''): string
    {
        if (is_array($args)) {
            $query = http_build_query($args);
            $separator = strpos($url, '?') !== false ? '&' : '?';
            return $url . $separator . $query;
        }
        return $url;
    }
}

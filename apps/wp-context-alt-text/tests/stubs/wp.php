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
    }
}

if (!class_exists('WP_REST_Request')) {
    class WP_REST_Request implements \ArrayAccess
    {
        /** @var array<string,mixed> */
        private $params;

        /**
         * @param array<string,mixed> $params
         */
        public function __construct(array $params = [])
        {
            $this->params = $params;
        }

        public function get_param(string $key)
        {
            return $this->params[$key] ?? null;
        }

        public function set_param(string $key, $value): self
        {
            $this->params[$key] = $value;

            return $this;
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

if (!class_exists('WP_CLI_Command')) {
    class WP_CLI_Command {}
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

if (!function_exists('add_action')) {
    function add_action($hook, $callback, $priority = 10, $accepted_args = 1): bool
    {
        if (!isset($GLOBALS['__cat_actions'][$hook])) {
            $GLOBALS['__cat_actions'][$hook] = [];
        }

        $GLOBALS['__cat_actions'][$hook][$priority][] = [
            'callback' => $callback,
            'accepted_args' => $accepted_args,
        ];

        return true;
    }
}

if (!function_exists('add_filter')) {
    function add_filter($hook, $callback, $priority = 10, $accepted_args = 1): bool
    {
        if (!isset($GLOBALS['__cat_filters'][$hook])) {
            $GLOBALS['__cat_filters'][$hook] = [];
        }

        $GLOBALS['__cat_filters'][$hook][$priority][] = [
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

        $GLOBALS['__cat_json_response'] = $response;

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

        $GLOBALS['__cat_json_response'] = $response;

        return $response;
    }
}

if (!function_exists('register_rest_route')) {
    function register_rest_route($namespace, $route, $args = [], $override = false): bool
    {
        $GLOBALS['__cat_rest_routes'][] = [
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
        return $value;
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

if (!function_exists('current_user_can')) {
    function current_user_can($capability, ...$args): bool
    {
        if (!isset($GLOBALS['__cat_current_user_capabilities'])) {
            $GLOBALS['__cat_current_user_capabilities'] = [];
        }

        $value = $GLOBALS['__cat_current_user_capabilities'][$capability] ?? null;

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

if (!function_exists('get_post')) {
    function get_post($postId)
    {
        return $GLOBALS['__cat_posts'][$postId] ?? false;
    }
}

if (!function_exists('get_post_mime_type')) {
    function get_post_mime_type($postId)
    {
        return $GLOBALS['__cat_attachment_mimes'][$postId] ?? false;
    }
}

if (!function_exists('wp_get_attachment_url')) {
    function wp_get_attachment_url($attachmentId)
    {
        return $GLOBALS['__cat_attachment_urls'][$attachmentId] ?? false;
    }
}

if (!function_exists('get_post_meta')) {
    function get_post_meta($postId, $key = '', $single = false)
    {
        if (!isset($GLOBALS['__cat_post_meta'][$postId])) {
            return $single ? '' : [];
        }

        if ($key === '' || $key === null) {
            return $GLOBALS['__cat_post_meta'][$postId];
        }

        if (!array_key_exists($key, $GLOBALS['__cat_post_meta'][$postId])) {
            return $single ? '' : [];
        }

        $value = $GLOBALS['__cat_post_meta'][$postId][$key];

        if ($single) {
            return $value;
        }

        return [$value];
    }
}

if (!function_exists('update_post_meta')) {
    function update_post_meta($postId, $metaKey, $metaValue)
    {
        if (!isset($GLOBALS['__cat_post_meta'])) {
            $GLOBALS['__cat_post_meta'] = [];
        }

        if (!isset($GLOBALS['__cat_post_meta'][$postId])) {
            $GLOBALS['__cat_post_meta'][$postId] = [];
        }

        $GLOBALS['__cat_post_meta'][$postId][$metaKey] = $metaValue;

        return true;
    }
}

if (!function_exists('delete_post_meta')) {
    function delete_post_meta($postId, $metaKey)
    {
        if (isset($GLOBALS['__cat_post_meta'][$postId][$metaKey])) {
            unset($GLOBALS['__cat_post_meta'][$postId][$metaKey]);
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

if (!function_exists('term_exists')) {
    function term_exists($term, $taxonomy)
    {
        if (!isset($GLOBALS['__cat_terms'][$taxonomy])) {
            return 0;
        }

        $slugMap = $GLOBALS['__cat_terms'][$taxonomy]['by_slug'] ?? [];

        if (is_numeric($term)) {
            $termId = (int) $term;
            if (isset($GLOBALS['__cat_terms'][$taxonomy]['by_id'][$termId])) {
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

if (!function_exists('wp_insert_term')) {
    function wp_insert_term($term, $taxonomy, $args = [])
    {
        if (!isset($GLOBALS['__cat_terms'][$taxonomy])) {
            $GLOBALS['__cat_terms'][$taxonomy] = [
                'next_id' => 1,
                'by_id' => [],
                'by_slug' => [],
            ];
        }

        $slug = isset($args['slug']) ? (string) $args['slug'] : sanitize_title($term);

        if ($slug === '') {
            $slug = sanitize_title($term . '-' . $GLOBALS['__cat_terms'][$taxonomy]['next_id']);
        }

        if (isset($GLOBALS['__cat_terms'][$taxonomy]['by_slug'][$slug])) {
            $existing = $GLOBALS['__cat_terms'][$taxonomy]['by_slug'][$slug];

            return [
                'term_id' => $existing,
                'term_taxonomy_id' => $existing,
            ];
        }

        $termId = $GLOBALS['__cat_terms'][$taxonomy]['next_id']++;

        $GLOBALS['__cat_terms'][$taxonomy]['by_id'][$termId] = [
            'term_id' => $termId,
            'term_taxonomy_id' => $termId,
            'name' => (string) $term,
            'slug' => $slug,
            'taxonomy' => $taxonomy,
        ];

        $GLOBALS['__cat_terms'][$taxonomy]['by_slug'][$slug] = $termId;

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

        $termIds = $GLOBALS['__cat_object_terms'][$taxonomy][$objectId] ?? [];
        $terms = [];

        foreach ($termIds as $termId) {
            if (!isset($GLOBALS['__cat_terms'][$taxonomy]['by_id'][$termId])) {
                continue;
            }

            $data = $GLOBALS['__cat_terms'][$taxonomy]['by_id'][$termId];
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

        if (!isset($GLOBALS['__cat_object_terms'][$taxonomy])) {
            $GLOBALS['__cat_object_terms'][$taxonomy] = [];
        }

        if ($append && isset($GLOBALS['__cat_object_terms'][$taxonomy][$objectId])) {
            $existing = $GLOBALS['__cat_object_terms'][$taxonomy][$objectId];
            $termIds = array_values(array_unique(array_merge($existing, $termIds)));
        }

        $GLOBALS['__cat_object_terms'][$taxonomy][$objectId] = $termIds;

        return $termIds;
    }
}

if (!function_exists('wp_generate_uuid4')) {
    function wp_generate_uuid4(): string
    {
        if (!isset($GLOBALS['__cat_uuid_counter'])) {
            $GLOBALS['__cat_uuid_counter'] = 0;
        }

        $GLOBALS['__cat_uuid_counter']++;

        return 'uuid-' . $GLOBALS['__cat_uuid_counter'];
    }
}

if (!function_exists('wp_upload_bits')) {
    function wp_upload_bits($name, $deprecated, $bits)
    {
        $directory = sys_get_temp_dir();
        $unique = uniqid('cat_upload_', true);
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
        if (!isset($GLOBALS['__cat_attachments'])) {
            $GLOBALS['__cat_attachments'] = [];
        }

        $id = isset($attachment['ID']) ? (int) $attachment['ID'] : (count($GLOBALS['__cat_attachments']) + 1);
        $GLOBALS['__cat_attachments'][$id] = array_merge($attachment, [
            'ID' => $id,
            'file' => $filename,
            'parent' => $parent,
        ]);

        return $id;
    }
}

if (!function_exists('get_attached_file')) {
    function get_attached_file($attachmentId)
    {
        return $GLOBALS['__cat_attachments'][$attachmentId]['file'] ?? null;
    }
}

if (!function_exists('get_transient')) {
    function get_transient($transient)
    {
        return $GLOBALS['__cat_transients'][$transient] ?? false;
    }
}

if (!function_exists('set_transient')) {
    function set_transient($transient, $value, $expiration = 0): bool
    {
        if (!isset($GLOBALS['__cat_transients'])) {
            $GLOBALS['__cat_transients'] = [];
        }

        $GLOBALS['__cat_transients'][$transient] = $value;

        return true;
    }
}

if (!function_exists('wp_next_scheduled')) {
    function wp_next_scheduled($hook, $args = [])
    {
        $key = $hook . '::' . md5(serialize($args));

        return $GLOBALS['__cat_scheduled'][$key]['timestamp'] ?? false;
    }
}

if (!function_exists('wp_schedule_single_event')) {
    function wp_schedule_single_event($timestamp, $hook, $args = []): void
    {
        $key = $hook . '::' . md5(serialize($args));
        $GLOBALS['__cat_scheduled'][$key] = [
            'timestamp' => $timestamp,
            'args' => $args,
        ];
    }
}

if (!function_exists('wp_clear_scheduled_hook')) {
    function wp_clear_scheduled_hook($hook, $args = []): void
    {
        $key = $hook . '::' . md5(serialize($args));
        unset($GLOBALS['__cat_scheduled'][$key]);
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
        if (empty($GLOBALS['__cat_filters'][$hook])) {
            return $value;
        }

        ksort($GLOBALS['__cat_filters'][$hook]);

        $args = func_get_args();
        array_shift($args); // remove hook name

        foreach ($GLOBALS['__cat_filters'][$hook] as $priority => $callbacks) {
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
        if (empty($GLOBALS['__cat_actions'][$hook])) {
            return;
        }

        ksort($GLOBALS['__cat_actions'][$hook]);

        foreach ($GLOBALS['__cat_actions'][$hook] as $priority => $callbacks) {
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
        $GLOBALS['__cat_registered_settings'][$option_name] = [
            'group' => $option_group,
            'args' => $args,
        ];

        return true;
    }
}

if (!function_exists('add_settings_section')) {
    function add_settings_section($id, $title, $callback, $page, $args = []): bool
    {
        $GLOBALS['__cat_settings_sections'][$page][$id] = [
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
        $GLOBALS['__cat_settings_fields'][$page][$section][$id] = [
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
        if (empty($GLOBALS['__cat_settings_sections'][$page])) {
            return;
        }

        foreach ($GLOBALS['__cat_settings_sections'][$page] as $sectionId => $section) {
            if (is_callable($section['callback'])) {
                $callback = $section['callback'];
                $args = $section['args'] ?? [];
                $callback($args);
            }

            if (empty($GLOBALS['__cat_settings_fields'][$page][$sectionId])) {
                continue;
            }

            foreach ($GLOBALS['__cat_settings_fields'][$page][$sectionId] as $field) {
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
    function wp_json_encode($data)
    {
        return json_encode($data);
    }
}

if (!function_exists('wp_remote_post')) {
    function wp_remote_post($url, $args = [])
    {
        if (!isset($GLOBALS['__cat_http_calls'])) {
            $GLOBALS['__cat_http_calls'] = [];
        }

        $GLOBALS['__cat_http_calls'][] = [
            'url' => $url,
            'args' => $args,
            'method' => 'POST',
            'body' => $args['body'] ?? '',
        ];

        if (!empty($GLOBALS['__cat_http_queue'])) {
            return array_shift($GLOBALS['__cat_http_queue']);
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
        if (!isset($GLOBALS['__cat_http_calls'])) {
            $GLOBALS['__cat_http_calls'] = [];
        }

        $GLOBALS['__cat_http_calls'][] = [
            'url' => $url,
            'args' => $args,
            'method' => 'GET',
            'body' => $args['body'] ?? '',
        ];

        if (!empty($GLOBALS['__cat_http_queue'])) {
            return array_shift($GLOBALS['__cat_http_queue']);
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
        if (!isset($GLOBALS['__cat_http_calls'])) {
            $GLOBALS['__cat_http_calls'] = [];
        }

        $method = isset($args['method']) ? strtoupper((string) $args['method']) : 'GET';

        $GLOBALS['__cat_http_calls'][] = [
            'url' => $url,
            'args' => $args,
            'method' => $method,
            'body' => $args['body'] ?? '',
        ];

        if (!empty($GLOBALS['__cat_http_queue'])) {
            return array_shift($GLOBALS['__cat_http_queue']);
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

        if ($type === 'timestamp') {
            return $gmt ? $timestamp : $timestamp;
        }

        if ($type === 'mysql') {
            return gmdate('Y-m-d H:i:s', $timestamp);
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

if (!function_exists('is_wp_error')) {
    function is_wp_error($thing): bool
    {
        return $thing instanceof WP_Error;
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

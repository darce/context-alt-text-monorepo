<?php

declare(strict_types=1);

/**
 * Development-time stubs for WordPress globals that Intelephense cannot resolve.
 *
 * The functions are conditionally declared so they won't override the real
 * implementations when WordPress is loaded. They return the widest practical
 * union types to satisfy static analysis.
 */

if (!function_exists('get_post_meta')) {
    /**
     * @param int    $postId
     * @param string $key
     * @param bool   $single
     * @return mixed
     */
    function get_post_meta(int $postId, string $key = '', bool $single = false)
    {
        return null;
    }
}

if (!function_exists('get_post')) {
    /**
     * @param int $postId
     * @return WP_Post|false
     */
    function get_post(int $postId)
    {
        return false;
    }
}

if (!function_exists('current_user_can')) {
    function current_user_can(string $capability, ...$args): bool
    {
        return true;
    }
}

if (!function_exists('get_post_modified_time')) {
    /**
     * @param string     $format
     * @param bool       $gmt
     * @param int|object $post
     * @param bool       $translate
     * @return string|int|false
     */
    function get_post_modified_time(string $format, bool $gmt = false, $post = null, bool $translate = true)
    {
        return false;
    }
}

if (!function_exists('get_post_mime_type')) {
    /**
     * @param int $postId
     * @return string|false
     */
    function get_post_mime_type(int $postId)
    {
        return false;
    }
}

if (!function_exists('wp_get_attachment_metadata')) {
    /**
     * @param int $attachmentId
     * @return array<string, mixed>|false
     */
    function wp_get_attachment_metadata(int $attachmentId)
    {
        return false;
    }
}

if (!function_exists('wp_get_attachment_image_url')) {
    /**
     * @param int         $attachmentId
     * @param string|int[]|string[] $size
     * @return string|false
     */
    function wp_get_attachment_image_url(int $attachmentId, $size = 'thumbnail')
    {
        return false;
    }
}

if (!function_exists('wp_get_attachment_url')) {
    /**
     * @param int $attachmentId
     * @return string|false
     */
    function wp_get_attachment_url(int $attachmentId)
    {
        return false;
    }
}

if (!function_exists('sanitize_text_field')) {
    /**
     * @param string $value
     */
    function sanitize_text_field(string $value): string
    {
        return $value;
    }
}

if (!function_exists('admin_url')) {
    /**
     * @param string $path
     * @param string $scheme
     * @return string
     */
    function admin_url(string $path = '', string $scheme = 'admin')
    {
        return '';
    }
}

if (!function_exists('wp_remote_post')) {
    /**
     * @param string               $url
     * @param array<string, mixed> $args
     * @return array<string, mixed>|\WP_Error
     */
    function wp_remote_post(string $url, array $args = [])
    {
        return [];
    }
}

if (!function_exists('wp_remote_retrieve_response_code')) {
    /**
     * @param array<string, mixed>|\WP_Error $response
     */
    function wp_remote_retrieve_response_code($response): int
    {
        return 200;
    }
}

if (!function_exists('wp_remote_retrieve_response_message')) {
    /**
     * @param array<string, mixed>|\WP_Error $response
     */
    function wp_remote_retrieve_response_message($response): string
    {
        return '';
    }
}

if (!function_exists('wp_remote_retrieve_body')) {
    /**
     * @param array<string, mixed>|\WP_Error $response
     */
    function wp_remote_retrieve_body($response): string
    {
        return '';
    }
}

if (!function_exists('wp_json_encode')) {
    /**
     * @param mixed $data
     */
    function wp_json_encode($data, int $options = 0, int $depth = 512): string
    {
        return json_encode($data, $options, $depth) ?: '';
    }
}

if (!function_exists('is_wp_error')) {
    /**
     * @param mixed $thing
     */
    function is_wp_error($thing): bool
    {
        return $thing instanceof WP_Error;
    }
}

if (!function_exists('get_transient')) {
    /**
     * @param string $transient
     * @return mixed
     */
    function get_transient(string $transient)
    {
        return false;
    }
}

if (!function_exists('set_transient')) {
    /**
     * @param string $transient
     * @param mixed  $value
     * @param int    $expiration
     */
    function set_transient(string $transient, $value, int $expiration = 0): bool
    {
        return true;
    }
}

if (!function_exists('add_action')) {
    function add_action(string $hook, callable $callback, int $priority = 10, int $acceptedArgs = 1): void
    {
        // no-op stub for IDEs and tests
        unset($hook, $callback, $priority, $acceptedArgs);
    }
}

if (!function_exists('register_rest_route')) {
    /**
     * @param array<string,mixed> $args
     */
    function register_rest_route(string $namespace, string $route, array $args, bool $override = false): bool
    {
        unset($namespace, $route, $args, $override);

        return true;
    }
}

if (!function_exists('rest_ensure_response')) {
    /**
     * @param mixed $response
     * @return WP_REST_Response|array<string,mixed>
     */
    function rest_ensure_response($response)
    {
        return $response instanceof WP_REST_Response ? $response : new WP_REST_Response($response);
    }
}

if (!function_exists('wp_generate_uuid4')) {
    function wp_generate_uuid4(): string
    {
        return '00000000-0000-4000-8000-000000000000';
    }
}

if (!class_exists('WP_Post')) {
    class WP_Post
    {
        /** @var int */
        public $ID = 0;

        /** @var string */
        public $post_title = '';

        /** @var string */
        public $post_modified_gmt = '';
    }
}

if (!class_exists('WP_Query')) {
    class WP_Query
    {
        /**
         * @var array<int, mixed>
         */
        public $posts = [];

        /** @var int */
        public $found_posts = 0;

        /** @var int */
        public $max_num_pages = 0;

        /**
         * @param array<string, mixed> $args
         */
        public function __construct(array $args = [])
        {
            $this->query($args);
        }

        /**
         * @param array<string, mixed> $args
         * @return array<int, mixed>
         */
        public function query(array $args = [])
        {
            return [];
        }
    }
}

if (!class_exists('WP_Error')) {
    class WP_Error
    {
        /** @var string */
        protected $message = '';

        public function __construct(string $code = '', string $message = '')
        {
            $this->message = $message;
        }

        public function get_error_message(): string
        {
            return $this->message;
        }
    }
}

if (!class_exists('WP_REST_Request')) {
    class WP_REST_Request implements \ArrayAccess
    {
        /** @var array<string,mixed> */
        protected $params = [];

        /** @param array<string,mixed> $params */
        public function __construct(array $params = [])
        {
            $this->params = $params;
        }

        /**
         * @param string $key
         * @return mixed
         */
        public function get_param($key)
        {
            return $this->params[$key] ?? null;
        }

        /**
         * @param string $key
         * @param mixed $default
         * @return mixed
         */
        public function get_param_with_default(string $key, $default = null)
        {
            return $this->params[$key] ?? $default;
        }

        public function __get(string $name)
        {
            return $this->params[$name] ?? null;
        }

        public function get_params(): array
        {
            return $this->params;
        }

        public function offsetExists($offset): bool
        {
            return array_key_exists((string) $offset, $this->params);
        }

        public function offsetGet($offset): mixed
        {
            return $this->params[$offset] ?? null;
        }

        public function offsetSet($offset, $value): void
        {
            if ($offset === null) {
                return;
            }

            $this->params[$offset] = $value;
        }

        public function offsetUnset($offset): void
        {
            unset($this->params[$offset]);
        }
    }
}

if (!class_exists('WP_REST_Response')) {
    class WP_REST_Response
    {
        /** @var array<string,string> */
        protected $headers = [];

        /** @var mixed */
        protected $data;

        public function __construct($data = null)
        {
            $this->data = $data;
        }

        public function header(string $key, string $value): void
        {
            $this->headers[$key] = $value;
        }

        public function get_data()
        {
            return $this->data;
        }

        /**
         * @return array<string,string>
         */
        public function get_headers(): array
        {
            return $this->headers;
        }
    }
}

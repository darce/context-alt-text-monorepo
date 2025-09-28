<?php

declare(strict_types=1);

require_once __DIR__ . '/stubs/wp.php';

spl_autoload_register(static function (string $class): void {
    $prefix = 'ContextAltText\\';

    if (strpos($class, $prefix) !== 0) {
        return;
    }

    $relative = substr($class, strlen($prefix));
    $path = __DIR__ . '/../src/' . str_replace('\\', '/', $relative) . '.php';

    if (is_readable($path)) {
        require_once $path;
    }
});

if (!defined('CONTEXT_ALT_TEXT_PLUGIN_DIR')) {
    define('CONTEXT_ALT_TEXT_PLUGIN_DIR', realpath(__DIR__ . '/..') . '/');
}

if (!defined('CONTEXT_ALT_TEXT_PLUGIN_URL')) {
    define('CONTEXT_ALT_TEXT_PLUGIN_URL', 'http://example.test/wp-content/plugins/context-alt-text/');
}

if (!defined('CONTEXT_ALT_TEXT_PLUGIN_BASENAME')) {
    define('CONTEXT_ALT_TEXT_PLUGIN_BASENAME', 'context-alt-text/context-alt-text.php');
}

if (!defined('CONTEXT_ALT_TEXT_VERSION')) {
    define('CONTEXT_ALT_TEXT_VERSION', 'test');
}

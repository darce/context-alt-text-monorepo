<?php

declare(strict_types=1);

require_once __DIR__ . '/stubs/wp.php';

spl_autoload_register(static function (string $class): void {
    $prefix = 'AltContext\\';

    if (strpos($class, $prefix) !== 0) {
        return;
    }

    $relative = substr($class, strlen($prefix));
    $path = __DIR__ . '/../src/' . str_replace('\\', '/', $relative) . '.php';

    if (is_readable($path)) {
        require_once $path;
    }
});

if (!defined('ACX_PLUGIN_DIR')) {
    define('ACX_PLUGIN_DIR', realpath(__DIR__ . '/..') . '/');
}

if (!defined('ACX_PLUGIN_URL')) {
    define('ACX_PLUGIN_URL', 'http://example.test/wp-content/plugins/alt-context/');
}

if (!defined('ACX_PLUGIN_BASENAME')) {
    define('ACX_PLUGIN_BASENAME', 'alt-context/alt-context.php');
}

if (!defined('ACX_VERSION')) {
    define('ACX_VERSION', 'test');
}

if (!defined('ACX_PLUGIN_FILE')) {
    define('ACX_PLUGIN_FILE', ACX_PLUGIN_DIR . 'alt-context.php');
}

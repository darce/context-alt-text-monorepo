<?php

declare(strict_types=1);

require_once dirname(__DIR__) . '/vendor/autoload.php';
require_once __DIR__ . '/stubs/wp.php';
require_once __DIR__ . '/stubs/class-null-clusters-repository.php';
require_once __DIR__ . '/stubs/class-null-identity-members-repository.php';
require_once __DIR__ . '/stubs/class-null-sync-state-repository.php';
require_once __DIR__ . '/Support/ClusterMutationsTestDoubles.php';
require_once __DIR__ . '/Support/FindsSqlQueries.php';
require_once __DIR__ . '/stubs/class-in-memory-conflict-repository.php';
require_once __DIR__ . '/stubs/class-in-memory-outbox-drain.php';
require_once __DIR__ . '/stubs/class-tracking-sync-state-repository.php';
require_once __DIR__ . '/stubs/class-spy-sync-pull-job.php';
require_once __DIR__ . '/stubs/class-targeted-spy-sync-pull-job.php';
require_once __DIR__ . '/stubs/class-snapshot-projector-clusters-spy.php';
require_once __DIR__ . '/stubs/class-snapshot-projector-members-spy.php';
require_once __DIR__ . '/stubs/class-snapshot-projector-sync-state-spy.php';

spl_autoload_register(static function (string $class): void {
    $prefix = 'AltContext\\';

    if (strpos($class, $prefix) !== 0) {
        return;
    }

    $relative = substr($class, strlen($prefix));
    $path = __DIR__ . '/../src/' . str_replace('\\', '/', $relative) . '.php';

    if (is_readable($path)) {
        require_once $path;
        return;
    }

    $parts = explode('/', str_replace('\\', '/', $relative));
    $className = array_pop($parts);
    $directories = array_map('strtolower', $parts);
    $kebab = strtolower((string) preg_replace('/([a-z0-9])([A-Z])/', '$1-$2', $className));
    $fallback = __DIR__ . '/../src/' . implode('/', $directories) . '/class-' . $kebab . '.php';

    if (is_readable($fallback)) {
        require_once $fallback;
        return;
    }

    if (str_ends_with($className, 'Interface')) {
        $baseName = substr($className, 0, -9);
        $baseKebab = strtolower((string) preg_replace('/([a-z0-9])([A-Z])/', '$1-$2', $baseName));
        $interfacePath = __DIR__ . '/../src/' . implode('/', $directories) . '/interface-' . $baseKebab . '.php';

        if (is_readable($interfacePath)) {
            require_once $interfacePath;
        }
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

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

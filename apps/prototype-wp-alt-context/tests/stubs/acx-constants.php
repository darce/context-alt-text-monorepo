<?php
/**
 * Plugin-defined constants for PHPStan static analysis.
 *
 * These constants are normally defined at runtime in alt-context.php.
 * PHPStan needs them declared ahead of time so it can resolve references
 * in src/ files that use ACX_* constants.
 *
 * @package AltContext
 */

declare(strict_types=1);

define('ACX_PLUGIN_FILE', __DIR__ . '/../../alt-context.php');
define('ACX_PLUGIN_DIR', __DIR__ . '/../../');
define('ACX_PLUGIN_URL', 'https://example.test/wp-content/plugins/alt-context/');
define('ACX_PLUGIN_BASENAME', 'alt-context/alt-context.php');
define('ACX_VERSION', '0.0.2');

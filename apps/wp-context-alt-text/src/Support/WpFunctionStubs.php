<?php

declare(strict_types=1);

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

<?php

declare(strict_types=1);

namespace ContextAltText\Api;

class Api
{
    public function init(): void
    {
        add_action('rest_api_init', [$this, 'register_routes']);
    }

    public function register_routes(): void
    {
        // REST routes will be registered alongside the internal admin SPA.
    }
}

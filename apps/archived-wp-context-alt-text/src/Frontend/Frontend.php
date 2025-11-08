<?php

declare(strict_types=1);

namespace ContextAltText\Frontend;

class Frontend
{
    public function bootstrap(): void
    {
        add_action('wp_enqueue_scripts', [$this, 'enqueue_script']);
        add_filter('wp_get_attachment_image_attributes', [$this, 'filter_image_attributes'], 10, 3);
    }

    public function enqueue_script(): void
    {
        // Frontend bundle enqueues are deferred until the public workflow ships.
    }

    public function get_config(): array
    {
        return [];
    }

    public function get_data(): array
    {
        return [];
    }

    public function filter_image_attributes(array $attr, $attachment, $size): array
    {
        // Placeholder for AI generated alt text injection.
        return $attr;
    }
}

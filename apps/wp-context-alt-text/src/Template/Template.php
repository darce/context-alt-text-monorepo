<?php

declare(strict_types=1);

namespace ContextAltText\Template;

class Template
{
    public function init(): void
    {
        add_filter('theme_page_templates', [$this, 'custom_template']);
        add_filter('template_include', [$this, 'load_custom_template']);
    }

    public function custom_template(array $templates): array
    {
        return $templates;
    }

    public function load_custom_template(string $template): string
    {
        return $template;
    }
}

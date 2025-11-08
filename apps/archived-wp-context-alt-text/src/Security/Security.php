<?php

declare(strict_types=1);

namespace ContextAltText\Security;

class Security
{
    public function can_manage_roster(): bool
    {
        return current_user_can('manage_options');
    }

    public function verify_admin_nonce(string $action, string $field, array $request): bool
    {
        $nonce = $request[$field] ?? '';
        return is_string($nonce) && wp_verify_nonce($nonce, $action) !== false;
    }

    public function sanitize_roster_data($data): ?array
    {
        if (!is_array($data)) {
            return null;
        }

        $sanitized = [];
        foreach ($data as $key => $value) {
            $sanitized[$key] = is_scalar($value) ? sanitize_text_field((string) $value) : $value;
        }

        return $sanitized;
    }

    public function create_nonce(string $action): string
    {
        return wp_create_nonce($action);
    }

    /**
     * Verify user has required capability
     *
     * @param string $capability The required capability (e.g., 'upload_files', 'manage_options')
     * @return bool True if user has capability
     */
    public function verifyCapability(string $capability): bool
    {
        return current_user_can($capability);
    }
}

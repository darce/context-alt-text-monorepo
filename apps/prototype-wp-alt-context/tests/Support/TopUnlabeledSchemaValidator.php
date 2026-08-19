<?php

declare(strict_types=1);

namespace AltContext\Tests\Support;

/**
 * Draft-07 checker for the top-unlabeled envelope fields this contract uses.
 */
final class TopUnlabeledSchemaValidator
{
    public const SCHEMA_RELATIVE = 'packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json';

    /**
     * @return array<string,mixed>
     */
    public static function loadSchema(): array
    {
        $path = self::resolveRepoPath(self::SCHEMA_RELATIVE);
        $decoded = json_decode((string) file_get_contents($path), true);
        if (! is_array($decoded)) {
            throw new \UnexpectedValueException('top-unlabeled schema is not an object');
        }

        return $decoded;
    }

    /**
     * @param array<string,mixed> $data
     */
    public static function validate(array $data): void
    {
        self::validateNode(self::loadSchema(), $data, '$');
    }

    /**
     * @param array<string,mixed> $schema
     */
    private static function validateNode(array $schema, mixed $data, string $path): void
    {
        $types = $schema['type'] ?? null;
        if (is_string($types)) {
            $types = [$types];
        }
        if (is_array($types)) {
            $matched = false;
            foreach ($types as $type) {
                if (self::valueHasType($data, (string) $type)) {
                    $matched = true;
                    break;
                }
            }
            if (! $matched) {
                throw new \UnexpectedValueException($path . ' type');
            }
        }

        if (isset($schema['minimum']) && is_numeric($data) && (float) $data < (float) $schema['minimum']) {
            throw new \UnexpectedValueException($path . ' minimum');
        }

        if (isset($schema['required']) && is_array($data)) {
            foreach ($schema['required'] as $required) {
                if (! array_key_exists((string) $required, $data)) {
                    throw new \UnexpectedValueException($path . ' required ' . $required);
                }
            }
        }

        if (($schema['type'] ?? null) === 'array' && is_array($data)) {
            if (isset($schema['minItems']) && count($data) < (int) $schema['minItems']) {
                throw new \UnexpectedValueException($path . ' minItems');
            }
            $item_schema = $schema['items'] ?? null;
            if (is_array($item_schema)) {
                foreach (array_values($data) as $index => $item) {
                    self::validateNode($item_schema, $item, $path . '[' . $index . ']');
                }
            }
        }

        if (($schema['type'] ?? null) === 'object' && is_array($data) && isset($schema['properties']) && is_array($schema['properties'])) {
            foreach ($schema['properties'] as $name => $child) {
                if (! is_array($child) || ! array_key_exists($name, $data)) {
                    continue;
                }
                self::validateNode($child, $data[$name], $path . '.' . $name);
            }
        }
    }

    private static function valueHasType(mixed $data, string $type): bool
    {
        return match ($type) {
            'object' => is_array($data) && (! array_is_list($data) || $data === []),
            'array' => is_array($data),
            'string' => is_string($data),
            'integer' => is_int($data),
            'number' => is_int($data) || is_float($data),
            'boolean' => is_bool($data),
            'null' => $data === null,
            default => false,
        };
    }

    private static function resolveRepoPath(string $relative): string
    {
        $cursor = __DIR__;
        for ($i = 0; $i < 8; $i++) {
            $candidate = $cursor . '/' . $relative;
            if (is_file($candidate)) {
                return $candidate;
            }
            $cursor = dirname($cursor);
        }

        throw new \UnexpectedValueException('Could not resolve ' . $relative);
    }
}

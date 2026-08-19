<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * R1-06: contract golden + local-projection fixture must satisfy the
 * top-unlabeled schema, including representatives.minItems = 1.
 *
 * @coversNothing
 */
class ClusterTopUnlabeledSchemaConsistencyTest extends TestCase
{
    private const SCHEMA_RELATIVE = 'packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json';
    private const GOLDEN_RELATIVE = 'packages/shared-contracts/recognition/cluster-top-unlabeled-response.golden.json';
    private const LOCAL_FIXTURE = __DIR__ . '/../fixtures/clusters-read/list_top_unlabeled_local_projection/response.json';
    private const PROXY_SUCCESS_FIXTURE = __DIR__ . '/../fixtures/clusters-read/list_top_unlabeled_proxy_success/response.json';
    private const PROXY_CANONICAL_FIXTURE = __DIR__ . '/../fixtures/clusters-read/list_top_unlabeled_proxy_canonical_envelope/response.json';

    public function testSchemaRequiresNonEmptyRepresentatives(): void
    {
        $schema = $this->loadJson($this->resolveRepoPath(self::SCHEMA_RELATIVE));
        $this->assertSame(1, $schema['properties']['clusters']['items']['properties']['representatives']['minItems']);
    }

    public function testContractGoldenValidatesAgainstSchema(): void
    {
        $schema = $this->loadJson($this->resolveRepoPath(self::SCHEMA_RELATIVE));
        $golden = $this->loadJson($this->resolveRepoPath(self::GOLDEN_RELATIVE));
        $this->assertSchemaValid($schema, $golden);
    }

    public function testLocalProjectionGoldenValidatesAgainstSchema(): void
    {
        $schema = $this->loadJson($this->resolveRepoPath(self::SCHEMA_RELATIVE));
        $fixture = $this->loadJson(self::LOCAL_FIXTURE);
        $this->assertSame('response', $fixture['type']);
        $this->assertSchemaValid($schema, $fixture['data']);
    }

    /**
     * R2-02 / R1-06 / R1-09: backend_proxy goldens must satisfy the same
     * representatives.minItems=1 contract as local_projection.
     */
    public function testProxySuccessGoldenValidatesAgainstSchema(): void
    {
        $schema = $this->loadJson($this->resolveRepoPath(self::SCHEMA_RELATIVE));
        $fixture = $this->loadJson(self::PROXY_SUCCESS_FIXTURE);
        $this->assertSame('response', $fixture['type']);
        $this->assertSchemaValid($schema, $fixture['data']);
    }

    public function testProxyCanonicalEnvelopeGoldenValidatesAgainstSchema(): void
    {
        $schema = $this->loadJson($this->resolveRepoPath(self::SCHEMA_RELATIVE));
        $fixture = $this->loadJson(self::PROXY_CANONICAL_FIXTURE);
        $this->assertSame('response', $fixture['type']);
        $this->assertSchemaValid($schema, $fixture['data']);
    }

    public function testMemberlessPayloadFailsMinItems(): void
    {
        $schema = $this->loadJson($this->resolveRepoPath(self::SCHEMA_RELATIVE));
        $invalid = $this->loadJson($this->resolveRepoPath(self::GOLDEN_RELATIVE));
        $invalid['clusters'][0]['representatives'] = [];

        $this->expectException(\UnexpectedValueException::class);
        $this->expectExceptionMessage('minItems');
        $this->assertSchemaValid($schema, $invalid);
    }

    /**
     * R4-02: repair_pending is required so dropping the key cannot stay green.
     */
    public function testGoldenWithoutRepairPendingFailsRequired(): void
    {
        $schema  = $this->loadJson($this->resolveRepoPath(self::SCHEMA_RELATIVE));
        $invalid = $this->loadJson($this->resolveRepoPath(self::GOLDEN_RELATIVE));
        unset($invalid['repair_pending']);

        $this->expectException(\UnexpectedValueException::class);
        $this->expectExceptionMessage('repair_pending');
        $this->assertSchemaValid($schema, $invalid);
    }

    /**
     * @return array<string,mixed>
     */
    private function loadJson(string $path): array
    {
        $this->assertFileExists($path);
        $decoded = json_decode((string) file_get_contents($path), true);
        $this->assertIsArray($decoded);
        return $decoded;
    }

    private function resolveRepoPath(string $relative): string
    {
        $cursor = __DIR__;
        for ($i = 0; $i < 8; $i++) {
            $candidate = $cursor . '/' . $relative;
            if (is_file($candidate)) {
                return $candidate;
            }
            $cursor = dirname($cursor);
        }
        $this->fail('Could not resolve ' . $relative);
    }

    /**
     * Minimal draft-07 checker for the fields this contract actually uses.
     *
     * @param array<string,mixed> $schema
     * @param mixed $data
     */
    private function assertSchemaValid(array $schema, mixed $data): void
    {
        $this->validateNode($schema, $data, '$');
    }

    /**
     * @param array<string,mixed> $schema
     */
    private function validateNode(array $schema, mixed $data, string $path): void
    {
        $types = $schema['type'] ?? null;
        if (is_string($types)) {
            $types = [$types];
        }
        if (is_array($types)) {
            $matched = false;
            foreach ($types as $type) {
                if ($this->valueHasType($data, (string) $type)) {
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
                    $this->validateNode($item_schema, $item, $path . '[' . $index . ']');
                }
            }
        }

        if (($schema['type'] ?? null) === 'object' && is_array($data) && isset($schema['properties']) && is_array($schema['properties'])) {
            foreach ($schema['properties'] as $name => $child) {
                if (! is_array($child) || ! array_key_exists($name, $data)) {
                    continue;
                }
                $this->validateNode($child, $data[$name], $path . '.' . $name);
            }
        }
    }

    private function valueHasType(mixed $data, string $type): bool
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
}

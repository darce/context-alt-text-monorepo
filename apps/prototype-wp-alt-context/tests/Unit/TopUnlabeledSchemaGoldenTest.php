<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * R1-06: shared-contracts top-unlabeled golden must satisfy the schema,
 * including representatives.minItems=1.
 *
 * @coversNothing
 */
class TopUnlabeledSchemaGoldenTest extends TestCase
{
    public function testSharedContractsGoldenSatisfiesTopUnlabeledSchema(): void
    {
        $schemaPath = dirname(__DIR__, 4) . '/packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json';
        $goldenPath = dirname(__DIR__, 4) . '/packages/shared-contracts/recognition/cluster-top-unlabeled-response.golden.json';

        $schema = json_decode((string) file_get_contents($schemaPath), true);
        $golden = json_decode((string) file_get_contents($goldenPath), true);

        $this->assertIsArray($schema);
        $this->assertIsArray($golden);
        $this->assertSame(1, $schema['properties']['clusters']['items']['properties']['representatives']['minItems'] ?? null);

        foreach ($golden['clusters'] as $cluster) {
            $this->assertIsArray($cluster['representatives']);
            $this->assertGreaterThanOrEqual(1, count($cluster['representatives']));
            $this->assertGreaterThanOrEqual(count($cluster['representatives']), $cluster['identity_count']);
        }
    }

    public function testEmptyRepresentativesViolateMinItems(): void
    {
        $schemaPath = dirname(__DIR__, 4) . '/packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json';
        $schema = json_decode((string) file_get_contents($schemaPath), true);
        $minItems = $schema['properties']['clusters']['items']['properties']['representatives']['minItems'] ?? 0;

        $this->assertSame(1, $minItems);
        $this->assertLessThan($minItems, count([]));
    }
}

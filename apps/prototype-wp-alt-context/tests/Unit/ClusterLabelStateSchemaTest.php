<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * UXW2-4-R8-03: shared-contract cluster item schemas declare label_state.
 *
 * @coversNothing
 */
class ClusterLabelStateSchemaTest extends TestCase
{
    private const LABEL_STATE_ENUM = ['person', 'unlabeled', 'unbound'];

    public function testClusterListAndTopUnlabeledSchemasRequireLabelStateEnumAndGoldensValidate(): void
    {
        $contracts = [
            [
                'schema' => 'schemas/recognition-cluster-list-response.schema.json',
                'golden' => 'recognition/cluster-list-response.golden.json',
            ],
            [
                'schema' => 'schemas/recognition-cluster-top-unlabeled-response.schema.json',
                'golden' => 'recognition/cluster-top-unlabeled-response.golden.json',
            ],
        ];

        foreach ($contracts as $contract) {
            $schema = $this->loadSharedContractJson($contract['schema']);
            $this->assertIsArray($schema);
            $item = $schema['properties']['clusters']['items'] ?? null;
            $this->assertIsArray($item, $contract['schema'] . ' must describe cluster items');
            $this->assertContains(
                'label_state',
                $item['required'] ?? [],
                $contract['schema'] . ' must require label_state'
            );
            $property = $item['properties']['label_state'] ?? null;
            $this->assertIsArray($property, $contract['schema'] . ' must declare label_state');
            $this->assertSame('string', $property['type'] ?? null);
            $this->assertSame(
                self::LABEL_STATE_ENUM,
                $property['enum'] ?? null,
                $contract['schema'] . ' label_state enum must be person|unlabeled|unbound'
            );

            $golden = $this->loadSharedContractJson($contract['golden']);
            $this->assertIsArray($golden);
            $this->assertIsArray($golden['clusters'] ?? null);
            foreach ($golden['clusters'] as $index => $cluster) {
                $this->assertIsArray($cluster);
                $this->assertArrayHasKey(
                    'label_state',
                    $cluster,
                    $contract['golden'] . " cluster[$index] must carry label_state"
                );
                $this->assertContains(
                    $cluster['label_state'],
                    $property['enum'],
                    $contract['golden'] . " cluster[$index] label_state must match schema enum"
                );
            }
        }
    }

    /**
     * @return array<string,mixed>
     */
    private function loadSharedContractJson(string $relative): array
    {
        $root = $this->findMonorepoRoot();
        $path = $root . '/packages/shared-contracts/' . $relative;
        $this->assertFileExists($path, $relative);
        $decoded = json_decode((string) file_get_contents($path), true);
        $this->assertIsArray($decoded, $relative . ' must decode as an object');

        return $decoded;
    }

    private function findMonorepoRoot(): string
    {
        $dir = __DIR__;
        for ($i = 0; $i < 8; $i++) {
            if (is_dir($dir . '/packages/shared-contracts/schemas')) {
                return $dir;
            }
            $parent = dirname($dir);
            if ($parent === $dir) {
                break;
            }
            $dir = $parent;
        }

        $this->fail('could not locate packages/shared-contracts from ' . __DIR__);
    }
}

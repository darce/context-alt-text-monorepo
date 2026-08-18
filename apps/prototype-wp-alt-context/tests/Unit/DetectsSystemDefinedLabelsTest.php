<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\DetectsSystemDefinedLabels;
use AltContext\Tests\TestCase;
use PHPUnit\Framework\Attributes\DataProvider;

/**
 * @covers \AltContext\Support\DetectsSystemDefinedLabels
 */
class DetectsSystemDefinedLabelsTest extends TestCase
{
    #[DataProvider('reservedLabelProvider')]
    public function testReservedLabelShapesAreDetected(string $label): void
    {
        $detector = new class() {
            use DetectsSystemDefinedLabels;

            public function isReserved(string $label): bool
            {
                return $this->is_reserved_label_shape($label);
            }
        };

        $this->assertTrue($detector->isReserved($label));
    }

    /** @return array<string,array{string}> */
    public static function reservedLabelProvider(): array
    {
        return [
            'hex machine label' => ['cluster-abcdef01'],
            'short underscore label' => ['cluster_7'],
            'trimmed label' => [' cluster-x '],
            'case-insensitive label' => ['CLUSTER-9'],
            'nbsp-prefixed reserved' => ["\u{00A0}cluster-9"],
            'ideographic-space-prefixed reserved' => ["\u{3000}cluster-9"],
        ];
    }

    #[DataProvider('nonReservedLabelProvider')]
    public function testNonReservedLabelsAreNotDetected(string $label): void
    {
        $detector = new class() {
            use DetectsSystemDefinedLabels;

            public function isReserved(string $label): bool
            {
                return $this->is_reserved_label_shape($label);
            }
        };

        $this->assertFalse($detector->isReserved($label));
    }

    /** @return array<string,array{string}> */
    public static function nonReservedLabelProvider(): array
    {
        return [
            'words' => ['Cluster Nine'],
            'no separator' => ['cluster'],
            'person name' => ['Alice'],
            'numbered person' => ['Person 2'],
            'empty' => [''],
            'mid-string cluster-9' => ['The cluster-9 team'],
            'mid-string cluster_x' => ['my cluster_x'],
        ];
    }

    public function testReservedLabelSqlPredicateCoversHyphenAndUnderscore(): void
    {
        $detector = new class() {
            use DetectsSystemDefinedLabels;

            public function sql(string $column): string
            {
                return $this->reserved_label_sql_predicate($column);
            }
        };

        $sql = $detector->sql('c.label');
        $this->assertStringContainsString("c.label LIKE 'cluster-%%'", $sql);
        $this->assertStringContainsString("c.label LIKE 'cluster\\_%%'", $sql);
    }
}

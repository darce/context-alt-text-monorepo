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
        $this->assertStringContainsString("LOWER(c.label) LIKE 'cluster-%%'", $sql);
        $this->assertStringContainsString("LOWER(c.label) LIKE 'cluster\\_%%'", $sql);
    }

    public function testProjectedLabelStateSqlNamesUnboundUnlabeledAndPerson(): void
    {
        $detector = new class() {
            use DetectsSystemDefinedLabels;

            public function sql(string $person, string $label): string
            {
                return $this->projected_cluster_label_state_sql($person, $label);
            }
        };

        $sql = $detector->sql('p.name', 'c.label');
        $this->assertStringContainsString("THEN 'person'", $sql);
        $this->assertStringContainsString("THEN 'unlabeled'", $sql);
        $this->assertStringContainsString("ELSE 'unbound'", $sql);
        $this->assertStringContainsString("LIKE 'cluster\\_%%'", $sql);
    }

    #[DataProvider('labelStateProvider')]
    public function testResolveClusterLabelStateNamesAuthority(?string $person, ?string $label, string $expected): void
    {
        $detector = new class() {
            use DetectsSystemDefinedLabels;

            public function state(?string $person, ?string $label): string
            {
                return $this->resolve_cluster_label_state($person, $label);
            }
        };

        $this->assertSame($expected, $detector->state($person, $label));
    }

    /** @return array<string,array{?string,?string,string}> */
    public static function labelStateProvider(): array
    {
        return [
            'bound person wins' => ['Ada Lovelace', 'Tory Guzman', 'person'],
            'unbound human' => [null, 'Tory Guzman', 'unbound'],
            'empty label' => [null, '', 'unlabeled'],
            'null label' => [null, null, 'unlabeled'],
            'hyphen auto label' => [null, 'cluster-abcdef01', 'unlabeled'],
            'underscore auto label' => [null, 'cluster_ab12', 'unlabeled'],
        ];
    }

    /**
     * M1: evaluate the CASE SQL against real person/label rows. Arm literals
     * are read from projected_cluster_label_state_sql(), so swapping the
     * unbound and unlabeled THEN/ELSE arms fails this test.
     */
    public function testProjectedLabelStateSqlClassifiesBoundPersonVersusUnboundHumanOnRealRows(): void
    {
        $detector = new class() {
            use DetectsSystemDefinedLabels;

            public function sql(string $person, string $label): string
            {
                return $this->projected_cluster_label_state_sql($person, $label);
            }

            public function reserved(string $label): bool
            {
                return $this->is_reserved_label_shape($label);
            }
        };

        $sql = $detector->sql('p.name', 'c.label');

        $this->assertSame(
            'person',
            $this->evaluateProjectedLabelStateSql($sql, 'Ada Lovelace', 'Ada Lovelace', $detector)
        );
        $this->assertSame(
            'unbound',
            $this->evaluateProjectedLabelStateSql($sql, null, 'Tory Guzman', $detector)
        );
        $this->assertSame(
            'unlabeled',
            $this->evaluateProjectedLabelStateSql($sql, null, '', $detector)
        );
        $this->assertSame(
            'unlabeled',
            $this->evaluateProjectedLabelStateSql($sql, null, 'cluster_ab12', $detector)
        );
    }

    /**
     * @param object{reserved(string): bool} $detector
     */
    private function evaluateProjectedLabelStateSql(string $sql, ?string $person, ?string $label, object $detector): string
    {
        if (preg_match("/THEN '([^']*)' WHEN .+ THEN '([^']*)' ELSE '([^']*)' END/s", $sql, $matches) !== 1) {
            self::fail('could not parse projected_cluster_label_state_sql CASE arms from: ' . $sql);
        }

        $personArm           = $matches[1];
        $emptyOrReservedArm  = $matches[2];
        $elseArm             = $matches[3];

        if (is_string($person) && '' !== $person) {
            return $personArm;
        }

        if (null === $label || '' === $label || $detector->reserved((string) $label)) {
            return $emptyOrReservedArm;
        }

        return $elseArm;
    }
}

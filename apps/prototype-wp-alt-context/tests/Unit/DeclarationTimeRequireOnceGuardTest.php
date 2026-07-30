<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use SplFileInfo;

use function array_values;
use function basename;
use function class_exists;
use function count;
use function escapeshellarg;
use function end;
use function explode;
use function file_get_contents;
use function implode;
use function in_array;
use function interface_exists;
use function is_array;
use function is_dir;
use function is_string;
use function ltrim;
use function preg_match;
use function preg_match_all;
use function realpath;
use function shell_exec;
use function sprintf;
use function str_contains;
use function str_starts_with;
use function substr;
use function sys_get_temp_dir;
use function token_get_all;
use function trait_exists;
use function trim;
use function var_export;

/**
 * R20-BR-15 / [rg-016] residual: defining files must require their own
 * declaration-time dependencies (extends / implements / in-class-body use Trait).
 *
 * Predicate settlement (R19-BR-24): this is NOT "every consumer requires every
 * type it names." Bootstrap-ordered freerides (admin SPA pages after
 * AbstractSpaPage, Admin after BatchLimits) are exempt when alt-context.php
 * loads the parent/trait before the child. File-scope `use` imports are not
 * themselves declaration-time loads — only in-class-body trait `use` counts —
 * but file-scope aliases must still resolve header short names (extends /
 * implements / trait use) to the imported symbol.
 *
 * @coversNothing
 */
class DeclarationTimeRequireOnceGuardTest extends TestCase
{
    /**
     * Bootstrap-ordered freerides documented against alt-context.php lines.
     * Keyed by src-relative path of the defining file, then by the short name
     * of the single declaration-time dependency that freerides on bootstrap
     * order. File-blanket keys would hide new undeclared deps on the same file.
     *
     * @var array<string, array<string, string>>
     */
    private const BOOTSTRAP_ORDERED_EXEMPTIONS = [
        'admin/class-admin.php' => [
            'BatchLimits' => 'alt-context.php:139 after trait-batch-limits.php:136',
        ],
        'admin/class-dashboard-page.php' => [
            'AbstractSpaPage' => 'alt-context.php:142 after class-abstract-spa-page.php:141',
        ],
        'admin/class-workbench-page.php' => [
            'AbstractSpaPage' => 'alt-context.php:143 after class-abstract-spa-page.php:141',
        ],
        'admin/class-roster-page.php' => [
            'AbstractSpaPage' => 'alt-context.php:144 after class-abstract-spa-page.php:141',
        ],
        'admin/class-settings-page.php' => [
            'AbstractSpaPage' => 'alt-context.php:145 after class-abstract-spa-page.php:141',
        ],
        'admin/class-description-history-page.php' => [
            'AbstractSpaPage' => 'alt-context.php:146 after class-abstract-spa-page.php:141',
        ],
        'admin/class-retention-page.php' => [
            'AbstractSpaPage' => 'alt-context.php:147 after class-abstract-spa-page.php:141',
        ],
    ];

    /**
     * SPL / PHP core / WordPress types the plugin does not define.
     *
     * @var list<string>
     */
    private const EXTERNAL_SHORT_NAMES = [
        'Throwable',
        'Stringable',
        'Countable',
        'Iterator',
        'IteratorAggregate',
        'ArrayAccess',
        'Serializable',
        'JsonSerializable',
        'Traversable',
        'UnitEnum',
        'BackedEnum',
        'Exception',
        'RuntimeException',
        'InvalidArgumentException',
        'LogicException',
        'BadMethodCallException',
        'UnexpectedValueException',
        'DomainException',
        'OutOfBoundsException',
        'OutOfRangeException',
        'OverflowException',
        'UnderflowException',
        'LengthException',
        'RangeException',
        'Error',
        'TypeError',
        'ValueError',
        'ArgumentCountError',
        'ArithmeticError',
        'DivisionByZeroError',
        'ParseError',
        'AssertionError',
        'UnhandledMatchError',
        'FiberError',
        'DateTime',
        'DateTimeImmutable',
        'DateTimeInterface',
        'DateInterval',
        'DatePeriod',
        'DateTimeZone',
        'stdClass',
        'Closure',
        'Generator',
        'WeakReference',
        'WeakMap',
        'SplFileInfo',
        'SplFileObject',
        'ArrayObject',
        'ArrayIterator',
        'RecursiveIteratorIterator',
        'RecursiveDirectoryIterator',
        'DirectoryIterator',
        'FilesystemIterator',
        'CallbackFilterIterator',
        'FilterIterator',
        'LimitIterator',
        'InfiniteIterator',
        'NoRewindIterator',
        'MultipleIterator',
        'AppendIterator',
        'CachingIterator',
        'RegexIterator',
        'RecursiveArrayIterator',
        'EmptyIterator',
        'IteratorIterator',
        'OuterIterator',
        'SeekableIterator',
        'SplObserver',
        'SplSubject',
        'SplObjectStorage',
        'SplPriorityQueue',
        'SplQueue',
        'SplStack',
        'SplHeap',
        'SplMaxHeap',
        'SplMinHeap',
        'SplFixedArray',
        'SplDoublyLinkedList',
        'SplTempFileObject',
        'WP_CLI_Command',
        'WP_Error',
        'WP_REST_Request',
        'WP_REST_Response',
        'WP_Query',
        'WP_Post',
        'WP_User',
        'WP_HTTP_Response',
    ];

    /** @var list<string> */
    private array $tempRoots = [];

    protected function tearDown(): void
    {
        foreach ($this->tempRoots as $root) {
            if (is_dir($root)) {
                $this->removeDirectory($root);
            }
        }
        $this->tempRoots = [];
        parent::tearDown();
    }

    public function testResidualDeclarationTimeGapsAreEmpty(): void
    {
        $gaps = $this->collectDeclarationTimeGaps($this->srcRoot());
        $this->assertSame(
            [],
            $gaps,
            "Defining files must require_once their own declaration-time deps:\n"
            . implode("\n", $gaps)
        );
    }

    /**
     * Bootstrap freeride must stay green: DashboardPage extends AbstractSpaPage
     * with no local require_once; alt-context.php loads abstract first.
     */
    public function testBootstrapOrderedAdminSurfaceIsNotAFinding(): void
    {
        $srcRoot = $this->srcRoot();
        $dashboardRel = 'admin/class-dashboard-page.php';
        $dashboardPath = $srcRoot . '/' . $dashboardRel;
        $dashboard = (string) file_get_contents($dashboardPath);

        $this->assertMatchesRegularExpression(
            '/class\s+DashboardPage\s+extends\s+AbstractSpaPage\b/',
            $dashboard,
            'DashboardPage must still extend AbstractSpaPage'
        );
        $this->assertFalse(
            $this->fileRequiresBasename($dashboard, 'class-abstract-spa-page.php'),
            'DashboardPage deliberately freerides on bootstrap order (no local require_once)'
        );
        $this->assertArrayHasKey(
            $dashboardRel,
            self::BOOTSTRAP_ORDERED_EXEMPTIONS,
            'DashboardPage must be on the bootstrap-ordered exemption list'
        );
        $this->assertArrayHasKey(
            'AbstractSpaPage',
            self::BOOTSTRAP_ORDERED_EXEMPTIONS[ $dashboardRel ],
            'DashboardPage exemption must be scoped to AbstractSpaPage only'
        );

        $gaps = $this->collectDeclarationTimeGaps($srcRoot);
        foreach ($gaps as $gap) {
            $this->assertStringNotContainsString(
                $dashboardRel,
                $gap,
                'Bootstrap-ordered DashboardPage must not appear in residual gaps'
            );
        }
    }

    /**
     * R20-BR-17: bootstrap exemption must be (file, dependency) pair-scoped, not
     * file-blanket. An exempted file with a second non-exempted declaration-time
     * dep must still report that dep.
     */
    public function testBootstrapExemptionIsRelationshipScopedNotFileBlanket(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'support/trait-batch-limits.php',
            "<?php\nnamespace AltContext\\Support;\ntrait BatchLimits {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'support/trait-other-limits.php',
            "<?php\nnamespace AltContext\\Support;\ntrait OtherLimits {}\n"
        );
        // Same relative path as the real freeride; exempts BatchLimits only.
        $this->writeFixture(
            $fixtureRoot,
            'admin/class-admin.php',
            "<?php\nnamespace AltContext\\Admin;\n"
            . "class Admin {\n"
            . "    use \\AltContext\\Support\\BatchLimits;\n"
            . "    use \\AltContext\\Support\\OtherLimits;\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);

        $batchExempted = true;
        $otherReported = false;
        foreach ($gaps as $gap) {
            if (str_contains($gap, 'admin/class-admin.php') && str_contains($gap, 'BatchLimits')) {
                $batchExempted = false;
            }
            if (
                str_contains($gap, 'admin/class-admin.php')
                && str_contains($gap, 'OtherLimits')
                && str_contains($gap, 'trait-other-limits.php')
            ) {
                $otherReported = true;
            }
        }

        $this->assertTrue(
            $batchExempted,
            "BatchLimits freeride must remain exempt; gaps:\n" . implode("\n", $gaps)
        );
        $this->assertTrue(
            $otherReported,
            "Second non-exempted declaration-time dep on an exempted file must be reported; gaps:\n"
            . implode("\n", $gaps)
        );
    }

    /**
     * File-scope `use Some\Thing;` is an import, not a declaration-time load.
     * Only in-class-body `use Trait;` counts.
     */
    public function testFileScopeUseImportIsNotFlagged(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'trait-maps-response-fields.php',
            "<?php\nnamespace AltContext\\Sovereign\\Mappers;\ntrait MapsResponseFields {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'class-file-scope-import-only.php',
            "<?php\nnamespace AltContext\\Sovereign\\Mappers;\n"
            . "use AltContext\\Sovereign\\Mappers\\MapsResponseFields;\n"
            . "class FileScopeImportOnly {\n"
            . "    public function x(): void {}\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $this->assertSame(
            [],
            $gaps,
            'File-scope use import must not be treated as declaration-time trait use; got: '
            . implode("\n", $gaps)
        );
    }

    /**
     * In-class-body trait use without require_once is a residual gap.
     */
    public function testInClassTraitUseWithoutRequireOnceIsFlagged(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'trait-maps-response-fields.php',
            "<?php\nnamespace AltContext\\Sovereign\\Mappers;\ntrait MapsResponseFields {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'class-missing-trait-require.php',
            "<?php\nnamespace AltContext\\Sovereign\\Mappers;\n"
            . "class MissingTraitRequire {\n"
            . "    use MapsResponseFields;\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $this->assertNotSame([], $gaps, 'In-class trait use without require_once must produce a gap');
        $matched = false;
        foreach ($gaps as $gap) {
            if (
                str_contains($gap, 'class-missing-trait-require.php')
                && str_contains($gap, 'MapsResponseFields')
                && str_contains($gap, 'trait-maps-response-fields.php')
            ) {
                $matched = true;
                break;
            }
        }
        $this->assertTrue(
            $matched,
            "Expected gap naming class-missing-trait-require.php + MapsResponseFields; got:\n"
            . implode("\n", $gaps)
        );
    }

    /**
     * Argument-less anonymous classes resolve parent/implements at `new` time,
     * not when the enclosing type is declared — must not attribute those deps
     * to the enclosing defining file.
     */
    public function testArgumentLessAnonymousClassExtendsIsNotDeclarationTimeDep(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'class-adapt-user.php',
            "<?php\nnamespace AltContext\\Support;\nclass AdaptUser {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'class-returns-anon.php',
            "<?php\nnamespace AltContext\\Support;\n"
            . "class ReturnsAnon {\n"
            . "    public function make(): object {\n"
            . "        return new class extends AdaptUser {};\n"
            . "    }\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        foreach ($gaps as $gap) {
            $this->assertStringNotContainsString(
                'class-returns-anon.php',
                $gap,
                'Argument-less anonymous class extends must not be a declaration-time gap; got: '
                . implode("\n", $gaps)
            );
        }
        $this->assertSame(
            [],
            $gaps,
            'Expected no gaps for argument-less anonymous class; got: ' . implode("\n", $gaps)
        );
    }

    /**
     * Traits are declaration-time consumers: in-body use of another plugin trait
     * without require_once is a residual gap (not exempt by filename alone).
     */
    public function testTraitConsumerInBodyUseWithoutRequireOnceIsFlagged(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'trait-inner.php',
            "<?php\nnamespace AltContext\\Support;\ntrait Inner {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'trait-outer.php',
            "<?php\nnamespace AltContext\\Support;\n"
            . "trait Outer {\n"
            . "    use Inner;\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $matched = false;
        foreach ($gaps as $gap) {
            if (
                str_contains($gap, 'trait-outer.php')
                && str_contains($gap, 'Inner')
                && str_contains($gap, 'trait-inner.php')
            ) {
                $matched = true;
                break;
            }
        }
        $this->assertTrue(
            $matched,
            "Expected gap naming trait-outer.php + Inner; got:\n" . implode("\n", $gaps)
        );
    }

    /**
     * Cold classmap: repaired ClusterResponseMapper declares when required first
     * with no Composer autoloader (style of DescribeControllerAutoloadTest).
     */
    public function testClusterResponseMapperDeclaresWithoutComposerClassmap(): void
    {
        $entrypoint = realpath(__DIR__ . '/../../src/sovereign/mappers/class-cluster-response-mapper.php');
        self::assertIsString($entrypoint, 'class-cluster-response-mapper.php must exist');

        $script = sprintf(
            'require %s; var_export(%s);',
            var_export($entrypoint, true),
            "class_exists('AltContext\\\\Sovereign\\\\Mappers\\\\ClusterResponseMapper', false)"
            . " && trait_exists('AltContext\\\\Sovereign\\\\Mappers\\\\MapsResponseFields', false)"
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            sprintf(
                'ClusterResponseMapper must self-require MapsResponseFields under cold classmap; got: %s',
                var_export($output, true)
            )
        );
    }

    /**
     * Cold classmap: repaired ClustersRepository declares its interface.
     */
    public function testClustersRepositoryDeclaresWithoutComposerClassmap(): void
    {
        $entrypoint = realpath(__DIR__ . '/../../src/sovereign/repositories/class-clusters-repository.php');
        self::assertIsString($entrypoint, 'class-clusters-repository.php must exist');

        $script = sprintf(
            'require %s; var_export(%s);',
            var_export($entrypoint, true),
            "class_exists('AltContext\\\\Sovereign\\\\Repositories\\\\ClustersRepository', false)"
            . " && interface_exists('AltContext\\\\Sovereign\\\\Repositories\\\\ClustersRepositoryInterface', false)"
        );
        $output = shell_exec(sprintf('php -r %s 2>&1', escapeshellarg($script)));
        $this->assertSame(
            'true',
            trim((string) $output),
            sprintf(
                'ClustersRepository must self-require its interface under cold classmap; got: %s',
                var_export($output, true)
            )
        );
    }

    /**
     * R21-BR-05: T_NAME_RELATIVE (`namespace\Foo`) is a real declaration-time
     * dependency form for extends, implements, and in-body trait use.
     */
    public function testRelativeNameFormExtendsImplementsTraitUseAreFlagged(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'class-parent-cls.php',
            "<?php\nnamespace AltContext\\Support;\nclass ParentCls {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'interface-iface.php',
            "<?php\nnamespace AltContext\\Support;\ninterface IFace {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'trait-t.php',
            "<?php\nnamespace AltContext\\Support;\ntrait T {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'class-child.php',
            "<?php\nnamespace AltContext\\Support;\n"
            . "class Child extends namespace\\ParentCls implements namespace\\IFace {\n"
            . "    use namespace\\T;\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $hasExtends = false;
        $hasImplements = false;
        $hasTrait = false;
        foreach ($gaps as $gap) {
            if (
                str_contains($gap, 'class-child.php')
                && str_contains($gap, 'extends')
                && str_contains($gap, 'ParentCls')
                && str_contains($gap, 'class-parent-cls.php')
            ) {
                $hasExtends = true;
            }
            if (
                str_contains($gap, 'class-child.php')
                && str_contains($gap, 'implements')
                && str_contains($gap, 'IFace')
                && str_contains($gap, 'interface-iface.php')
            ) {
                $hasImplements = true;
            }
            if (
                str_contains($gap, 'class-child.php')
                && str_contains($gap, 'use-trait')
                && str_contains($gap, 'T')
                && str_contains($gap, 'trait-t.php')
            ) {
                $hasTrait = true;
            }
        }
        $this->assertTrue(
            $hasExtends,
            "Expected relative-form extends ParentCls gap; got:\n" . implode("\n", $gaps)
        );
        $this->assertTrue(
            $hasImplements,
            "Expected relative-form implements IFace gap; got:\n" . implode("\n", $gaps)
        );
        $this->assertTrue(
            $hasTrait,
            "Expected relative-form use-trait T gap; got:\n" . implode("\n", $gaps)
        );
    }

    /**
     * R21-BR-06 leg A: extends + implements sharing a short name must both
     * survive collection — short-name map overwrite masks the first.
     */
    public function testShortNameCollisionExtendsImplementsIsNotMasked(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'class-helper.php',
            "<?php\nnamespace AltContext\\Ns1;\nclass Helper {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'interface-helper.php',
            "<?php\nnamespace AltContext\\Ns2;\ninterface Helper {}\n"
        );
        // Only the interface is required — the class parent must still gap.
        $this->writeFixture(
            $fixtureRoot,
            'class-collision-consumer.php',
            "<?php\nnamespace AltContext\\App;\n"
            . "require_once __DIR__ . '/interface-helper.php';\n"
            . "class CollisionConsumer extends \\AltContext\\Ns1\\Helper implements \\AltContext\\Ns2\\Helper {}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $classParentReported = false;
        foreach ($gaps as $gap) {
            if (
                str_contains($gap, 'class-collision-consumer.php')
                && str_contains($gap, 'extends')
                && str_contains($gap, 'Helper')
                && str_contains($gap, 'class-helper.php')
            ) {
                $classParentReported = true;
            }
        }
        $this->assertTrue(
            $classParentReported,
            "Short-name collision must not mask extends Helper (class) when implements Helper is required; gaps:\n"
            . implode("\n", $gaps)
        );
    }

    /**
     * R21-BR-06 leg B: extends + in-body trait use sharing a short name must
     * both survive — same overwrite bug, second write path.
     */
    public function testShortNameCollisionExtendsTraitUseIsNotMasked(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'class-shared.php',
            "<?php\nnamespace AltContext\\Support;\nclass Shared {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'trait-shared.php',
            "<?php\nnamespace AltContext\\Support;\ntrait Shared {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'class-extends-and-trait.php',
            "<?php\nnamespace AltContext\\Support;\n"
            . "require_once __DIR__ . '/trait-shared.php';\n"
            . "class ExtendsAndTrait extends Shared {\n"
            . "    use Shared;\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $extendsReported = false;
        foreach ($gaps as $gap) {
            if (
                str_contains($gap, 'class-extends-and-trait.php')
                && str_contains($gap, 'extends')
                && str_contains($gap, 'Shared')
                && str_contains($gap, 'class-shared.php')
            ) {
                $extendsReported = true;
            }
        }
        $this->assertTrue(
            $extendsReported,
            "Short-name collision must not mask extends Shared when trait use Shared is required; gaps:\n"
            . implode("\n", $gaps)
        );
    }

    /**
     * R21-BR-07: file-scope import aliases must resolve header dep names.
     * Covers plain, aliased, grouped, and grouped-aliased forms.
     */
    public function testFileScopeAliasResolvesHeaderDepNames(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'class-base-class.php',
            "<?php\nnamespace AltContext\\Support;\nclass BaseClass {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'interface-base-iface.php',
            "<?php\nnamespace AltContext\\Support;\ninterface BaseIface {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'trait-base-trait.php',
            "<?php\nnamespace AltContext\\Support;\ntrait BaseTrait {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'class-other-helper.php',
            "<?php\nnamespace AltContext\\Support;\nclass OtherHelper {}\n"
        );

        // Grouped-aliased extends + plain-aliased implements + plain use-as for trait.
        $this->writeFixture(
            $fixtureRoot,
            'class-aliased-child.php',
            "<?php\nnamespace AltContext\\App;\n"
            . "use AltContext\\Support\\{BaseClass as ParentAlias, OtherHelper};\n"
            . "use AltContext\\Support\\BaseIface as IFaceAlias;\n"
            . "use AltContext\\Support\\BaseTrait as TraitAlias;\n"
            . "class AliasedChild extends ParentAlias implements IFaceAlias {\n"
            . "    use TraitAlias;\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $hasExtends = false;
        $hasImplements = false;
        $hasTrait = false;
        foreach ($gaps as $gap) {
            if (
                str_contains($gap, 'class-aliased-child.php')
                && str_contains($gap, 'extends')
                && str_contains($gap, 'BaseClass')
                && str_contains($gap, 'class-base-class.php')
            ) {
                $hasExtends = true;
            }
            if (
                str_contains($gap, 'class-aliased-child.php')
                && str_contains($gap, 'implements')
                && str_contains($gap, 'BaseIface')
                && str_contains($gap, 'interface-base-iface.php')
            ) {
                $hasImplements = true;
            }
            if (
                str_contains($gap, 'class-aliased-child.php')
                && str_contains($gap, 'use-trait')
                && str_contains($gap, 'BaseTrait')
                && str_contains($gap, 'trait-base-trait.php')
            ) {
                $hasTrait = true;
            }
        }
        $this->assertTrue(
            $hasExtends,
            "Aliased extends ParentAlias→BaseClass must gap; got:\n" . implode("\n", $gaps)
        );
        $this->assertTrue(
            $hasImplements,
            "Aliased implements IFaceAlias→BaseIface must gap; got:\n" . implode("\n", $gaps)
        );
        $this->assertTrue(
            $hasTrait,
            "Aliased use-trait TraitAlias→BaseTrait must gap; got:\n" . implode("\n", $gaps)
        );

        // OtherHelper is imported but not a declaration-time dep — must not appear.
        foreach ($gaps as $gap) {
            $this->assertStringNotContainsString(
                'OtherHelper',
                $gap,
                'File-scope import without header use must not create a gap'
            );
        }
    }

    /**
     * R21-BR-16: enum-*.php consumers with declaration-time implements must be scanned.
     */
    public function testEnumConsumerImplementsWithoutRequireOnceIsFlagged(): void
    {
        $fixtureRoot = $this->makeFixtureRoot();
        $this->writeFixture(
            $fixtureRoot,
            'interface-has-label.php',
            "<?php\nnamespace AltContext\\Support;\ninterface HasLabel {}\n"
        );
        $this->writeFixture(
            $fixtureRoot,
            'enum-status.php',
            "<?php\nnamespace AltContext\\Support;\n"
            . "enum Status implements HasLabel {\n"
            . "    case Ready;\n"
            . "}\n"
        );

        $gaps = $this->collectDeclarationTimeGaps($fixtureRoot);
        $matched = false;
        foreach ($gaps as $gap) {
            if (
                str_contains($gap, 'enum-status.php')
                && str_contains($gap, 'implements')
                && str_contains($gap, 'HasLabel')
                && str_contains($gap, 'interface-has-label.php')
            ) {
                $matched = true;
                break;
            }
        }
        $this->assertTrue(
            $matched,
            "Expected enum-status.php implements HasLabel gap; got:\n" . implode("\n", $gaps)
        );
    }

    /**
     * @return list<string>
     */
    private function collectDeclarationTimeGaps(string $scanRoot): array
    {
        $scanRoot = (string) realpath($scanRoot);
        $index = $this->indexPluginSymbols($scanRoot);
        $gaps = [];

        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($scanRoot, RecursiveDirectoryIterator::SKIP_DOTS)
        );
        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if ( ! $file->isFile()) {
                continue;
            }
            $basename = $file->getFilename();
            // Consumers: class/interface/trait/enum defining files. Traits and
            // enums can carry declaration-time deps (use Trait / implements).
            if ( ! preg_match('/^(class|interface|trait|enum)-.+\.php$/', $basename)) {
                continue;
            }

            $path = $file->getPathname();
            $code = (string) file_get_contents($path);
            $requires = $this->collectRequireOnceBasenames($code);
            $deps = $this->collectDeclarationTimeDeps($code);
            $rel = ltrim(str_replace($scanRoot, '', $path), '/');

            foreach ($deps as $dep) {
                $short = $dep['short'];
                $context = $dep['context'];
                if ($this->isExternalName($short)) {
                    continue;
                }
                if ( ! isset($index[ $short ])) {
                    continue;
                }
                $chosen = $this->chooseDefiningFile($index[ $short ], $context);
                $need = $chosen['basename'];
                if ($basename === $need) {
                    continue;
                }
                if (in_array($need, $requires, true)) {
                    continue;
                }
                // Relationship-scoped: only the documented (file, dep) freeride
                // is excused — a second undeclared dep on the same file is not.
                if (isset(self::BOOTSTRAP_ORDERED_EXEMPTIONS[ $rel ][ $short ])) {
                    continue;
                }
                $gaps[] = sprintf(
                    '%s — %s %s (need %s)',
                    $rel,
                    $context,
                    $short,
                    $need
                );
            }
        }

        sort($gaps);
        return $gaps;
    }

    /**
     * @return array<string, list<array{path: string, kind: string, basename: string}>>
     */
    private function indexPluginSymbols(string $scanRoot): array
    {
        $byShort = [];
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($scanRoot, RecursiveDirectoryIterator::SKIP_DOTS)
        );
        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if ( ! $file->isFile()) {
                continue;
            }
            $basename = $file->getFilename();
            if ( ! preg_match('/^(class|interface|trait)-.+\.php$/', $basename)) {
                continue;
            }
            $path = $file->getPathname();
            $code = (string) file_get_contents($path);
            $tokens = token_get_all($code);
            $n = count($tokens);
            for ($i = 0; $i < $n; $i++) {
                $t = $tokens[ $i ];
                if ( ! is_array($t)) {
                    continue;
                }
                if ( ! in_array($t[0], [ T_CLASS, T_INTERFACE, T_TRAIT ], true)) {
                    continue;
                }
                if (T_CLASS === $t[0]) {
                    for ($k = $i + 1; $k < $n; $k++) {
                        $tk = $tokens[ $k ];
                        if (is_array($tk) && T_WHITESPACE === $tk[0]) {
                            continue;
                        }
                        if ('(' === $tk) {
                            continue 2;
                        }
                        break;
                    }
                }
                for ($k = $i + 1; $k < $n; $k++) {
                    $tk = $tokens[ $k ];
                    if (is_array($tk) && T_WHITESPACE === $tk[0]) {
                        continue;
                    }
                    if (is_array($tk) && T_STRING === $tk[0]) {
                        $kind = T_CLASS === $t[0] ? 'class' : ( T_INTERFACE === $t[0] ? 'interface' : 'trait' );
                        $byShort[ $tk[1] ][] = [
                            'path' => $path,
                            'kind' => $kind,
                            'basename' => $basename,
                        ];
                    }
                    break;
                }
            }
        }
        return $byShort;
    }

    /**
     * @param list<array{path: string, kind: string, basename: string}> $candidates
     * @return array{path: string, kind: string, basename: string}
     */
    private function chooseDefiningFile(array $candidates, string $context): array
    {
        $want = null;
        if ('use-trait' === $context) {
            $want = 'trait';
        } elseif ('implements' === $context) {
            $want = 'interface';
        }
        if (null !== $want) {
            foreach ($candidates as $c) {
                if ($want === $c['kind']) {
                    return $c;
                }
            }
        }
        // extends may be class or interface
        if ('extends' === $context) {
            foreach ($candidates as $c) {
                if ('class' === $c['kind'] || 'interface' === $c['kind']) {
                    return $c;
                }
            }
        }
        return $candidates[0];
    }

    /**
     * Name tokens accepted for declaration-time type references. Includes
     * T_NAME_RELATIVE (`namespace\Foo`) which resolves against the file namespace.
     *
     * @var list<int>
     */
    private const NAME_TOKEN_IDS = [
        T_STRING,
        T_NAME_QUALIFIED,
        T_NAME_FULLY_QUALIFIED,
        T_NAME_RELATIVE,
    ];

    /**
     * @return list<array{short: string, context: string}>
     */
    private function collectDeclarationTimeDeps(string $code): array
    {
        $tokens = token_get_all($code);
        // Keyed by "context\0short" so two relationships sharing a short name
        // (extends Helper + implements Helper) cannot overwrite each other.
        $depsByKey = [];
        $n = count($tokens);
        $brace_depth = 0;
        $class_brace = null;
        $in_class = false;
        $after_kw = false;
        $expect_ext = false;
        $expect_impl = false;
        $in_header = false;
        $fileNamespace = '';
        $aliases = [];

        for ($i = 0; $i < $n; $i++) {
            $t = $tokens[ $i ];
            if ( ! is_array($t)) {
                if ('{' === $t) {
                    $brace_depth++;
                    if ($in_header && null === $class_brace) {
                        $class_brace = $brace_depth;
                        $in_class = true;
                        $in_header = false;
                        $after_kw = false;
                        $expect_ext = false;
                        $expect_impl = false;
                    }
                } elseif ('}' === $t) {
                    if ($in_class && $brace_depth === $class_brace) {
                        $in_class = false;
                        $class_brace = null;
                    }
                    $brace_depth--;
                }
                continue;
            }

            [ $id, $text ] = [ $t[0], $t[1] ];

            if (T_NAMESPACE === $id) {
                $fileNamespace = $this->parseNamespaceName($tokens, $i + 1, $n);
                continue;
            }

            // File-scope imports: build alias map; not declaration-time loads.
            if ( ! $in_class && T_USE === $id) {
                $this->absorbFileScopeUse($tokens, $i, $n, $aliases);
                continue;
            }

            if (in_array($id, [ T_CLASS, T_INTERFACE, T_TRAIT, T_ENUM ], true)) {
                $anon = false;
                if (T_CLASS === $id) {
                    // Anonymous: `new class`, `new class (...)`, `new class extends`,
                    // `new class implements`. Named: `class Identifier`.
                    for ($k = $i + 1; $k < $n; $k++) {
                        $tk = $tokens[ $k ];
                        if (is_array($tk) && in_array($tk[0], [ T_WHITESPACE, T_COMMENT, T_DOC_COMMENT ], true)) {
                            continue;
                        }
                        if ( ! is_array($tk) || T_STRING !== $tk[0]) {
                            $anon = true;
                        }
                        break;
                    }
                }
                if ( ! $anon) {
                    $in_header = true;
                    $after_kw = true;
                    $expect_ext = false;
                    $expect_impl = false;
                }
                continue;
            }

            // Only named-type headers own extends/implements as declaration-time
            // deps. Anonymous `new class extends X` resolves at `new` execution.
            if ($in_header && T_EXTENDS === $id) {
                $expect_ext = true;
                $expect_impl = false;
                $after_kw = false;
                continue;
            }
            if ($in_header && T_IMPLEMENTS === $id) {
                $expect_impl = true;
                $expect_ext = false;
                $after_kw = false;
                continue;
            }

            if ($after_kw && in_array($id, self::NAME_TOKEN_IDS, true)) {
                $after_kw = false;
                continue;
            }

            if ($in_header && ( $expect_ext || $expect_impl ) && in_array($id, self::NAME_TOKEN_IDS, true)) {
                $short = $this->resolveDepShortName($text, $fileNamespace, $aliases);
                $context = $expect_ext ? 'extends' : 'implements';
                $depsByKey[ $context . "\0" . $short ] = [
                    'short' => $short,
                    'context' => $context,
                ];
            }

            // Trait use only inside class body at class brace depth.
            // File-scope `use Foo\Bar;` has in_class=false (handled above).
            if ($in_class && $brace_depth === $class_brace && T_USE === $id) {
                $expect_name = true;
                $skip = false;
                for ($j = $i + 1; $j < $n; $j++) {
                    $tj = $tokens[ $j ];
                    if (';' === $tj) {
                        break;
                    }
                    if ('{' === $tj) {
                        $d = 1;
                        for (++$j; $j < $n; $j++) {
                            if ('{' === $tokens[ $j ]) {
                                $d++;
                            } elseif ('}' === $tokens[ $j ]) {
                                $d--;
                                if (0 === $d) {
                                    break;
                                }
                            }
                        }
                        continue;
                    }
                    if ( ! is_array($tj)) {
                        if (',' === $tj) {
                            $expect_name = true;
                            $skip = false;
                        }
                        continue;
                    }
                    if (in_array($tj[0], [ T_WHITESPACE, T_COMMENT, T_DOC_COMMENT ], true)) {
                        continue;
                    }
                    if (T_AS === $tj[0] || T_INSTEADOF === $tj[0]) {
                        $skip = true;
                        $expect_name = false;
                        continue;
                    }
                    if ($skip) {
                        continue;
                    }
                    if ($expect_name && in_array($tj[0], self::NAME_TOKEN_IDS, true)) {
                        $short = $this->resolveDepShortName($tj[1], $fileNamespace, $aliases);
                        $depsByKey[ 'use-trait' . "\0" . $short ] = [
                            'short' => $short,
                            'context' => 'use-trait',
                        ];
                        $expect_name = false;
                    }
                }
            }
        }

        return array_values($depsByKey);
    }

    /**
     * @param array<int, string|array{0:int,1:string,2?:int}> $tokens
     */
    private function parseNamespaceName(array $tokens, int $from, int $n): string
    {
        for ($k = $from; $k < $n; $k++) {
            $tk = $tokens[ $k ];
            if (is_array($tk) && in_array($tk[0], [ T_WHITESPACE, T_COMMENT, T_DOC_COMMENT ], true)) {
                continue;
            }
            if (is_array($tk) && in_array($tk[0], [ T_STRING, T_NAME_QUALIFIED ], true)) {
                return $tk[1];
            }
            // `namespace {` / empty name
            return '';
        }
        return '';
    }

    /**
     * Absorb one file-scope `use` into the alias map (plain, aliased, grouped,
     * grouped-aliased). Skips `use function` / `use const`.
     *
     * @param array<int, string|array{0:int,1:string,2?:int}> $tokens
     * @param array<string, string>                           $aliases alias short => real short
     */
    private function absorbFileScopeUse(array $tokens, int $useIndex, int $n, array &$aliases): void
    {
        $i = $useIndex + 1;
        while ($i < $n && is_array($tokens[ $i ]) && in_array($tokens[ $i ][0], [ T_WHITESPACE, T_COMMENT, T_DOC_COMMENT ], true)) {
            $i++;
        }
        if ($i >= $n) {
            return;
        }
        if (is_array($tokens[ $i ]) && in_array($tokens[ $i ][0], [ T_FUNCTION, T_CONST ], true)) {
            return;
        }

        $prefix = '';
        $currentName = null;
        $inGroup = false;

        for (; $i < $n; $i++) {
            $t = $tokens[ $i ];
            if (';' === $t) {
                if (null !== $currentName) {
                    $short = $this->lastNameSegment($currentName);
                    $aliases[ $short ] = $short;
                }
                break;
            }
            if (is_array($t) && in_array($t[0], [ T_WHITESPACE, T_COMMENT, T_DOC_COMMENT ], true)) {
                continue;
            }
            if ('{' === $t) {
                $prefix = (string) $currentName;
                $currentName = null;
                $inGroup = true;
                continue;
            }
            if ('}' === $t) {
                $inGroup = false;
                continue;
            }
            if (',' === $t) {
                if (null !== $currentName) {
                    $short = $this->lastNameSegment($currentName);
                    $aliases[ $short ] = $short;
                    $currentName = null;
                }
                continue;
            }
            if (is_array($t) && T_AS === $t[0]) {
                $j = $i + 1;
                while ($j < $n && is_array($tokens[ $j ]) && in_array($tokens[ $j ][0], [ T_WHITESPACE, T_COMMENT, T_DOC_COMMENT ], true)) {
                    $j++;
                }
                if ($j < $n && is_array($tokens[ $j ]) && T_STRING === $tokens[ $j ][0] && null !== $currentName) {
                    $aliases[ $tokens[ $j ][1] ] = $this->lastNameSegment($currentName);
                    $currentName = null;
                    $i = $j;
                }
                continue;
            }
            if (is_array($t) && in_array($t[0], self::NAME_TOKEN_IDS, true)) {
                $piece = ltrim($t[1], '\\');
                if ($inGroup) {
                    $currentName = '' === $prefix ? $piece : $prefix . '\\' . $piece;
                } elseif (null === $currentName) {
                    $currentName = $piece;
                } else {
                    $currentName .= '\\' . $piece;
                }
                continue;
            }
            if (is_array($t) && T_NS_SEPARATOR === $t[0]) {
                // Separator between group prefix and `{` (e.g. Support\{).
                continue;
            }
        }
    }

    /**
     * @param array<string, string> $aliases
     */
    private function resolveDepShortName(string $tokenText, string $fileNamespace, array $aliases): string
    {
        $short = $this->shortNameFromNameToken($tokenText, $fileNamespace);
        if (isset($aliases[ $short ])) {
            return $aliases[ $short ];
        }
        return $short;
    }

    private function shortNameFromNameToken(string $text, string $fileNamespace): string
    {
        // T_NAME_RELATIVE: `namespace\Foo` → current-namespace\Foo
        if (str_starts_with($text, 'namespace\\')) {
            $rest = substr($text, strlen('namespace\\'));
            $fqcn = '' === $fileNamespace ? $rest : $fileNamespace . '\\' . $rest;
            return $this->lastNameSegment($fqcn);
        }
        return $this->lastNameSegment(ltrim($text, '\\'));
    }

    private function lastNameSegment(string $name): string
    {
        $parts = explode('\\', $name);
        return (string) end($parts);
    }

    /**
     * @return list<string>
     */
    private function collectRequireOnceBasenames(string $code): array
    {
        $tokens = token_get_all($code);
        $requires = [];
        $n = count($tokens);
        for ($i = 0; $i < $n; $i++) {
            if ( ! is_array($tokens[ $i ]) || T_REQUIRE_ONCE !== $tokens[ $i ][0]) {
                continue;
            }
            $expr = '';
            for ($j = $i + 1; $j < $n; $j++) {
                $t = $tokens[ $j ];
                if (';' === $t) {
                    break;
                }
                $expr .= is_array($t) ? $t[1] : $t;
            }
            if (preg_match_all('/[\'"]([^\'"]+\.php)[\'"]/', $expr, $mm)) {
                foreach ($mm[1] as $p) {
                    $requires[] = basename($p);
                }
            }
        }
        return $requires;
    }

    private function fileRequiresBasename(string $code, string $basename): bool
    {
        return in_array($basename, $this->collectRequireOnceBasenames($code), true);
    }

    private function isExternalName(string $short): bool
    {
        if (str_starts_with($short, 'WP_')) {
            return true;
        }
        return in_array($short, self::EXTERNAL_SHORT_NAMES, true);
    }

    private function srcRoot(): string
    {
        $root = realpath(__DIR__ . '/../../src');
        self::assertIsString($root, 'src/ must exist');
        return $root;
    }

    private function makeFixtureRoot(): string
    {
        $root = sys_get_temp_dir() . '/acx_decl_time_' . bin2hex(random_bytes(4));
        if ( ! mkdir($root) && ! is_dir($root)) {
            self::fail('Could not create fixture root');
        }
        $this->tempRoots[] = $root;
        return $root;
    }

    private function writeFixture(string $root, string $relative, string $contents): void
    {
        $path = $root . '/' . $relative;
        $dir = dirname($path);
        if ( ! is_dir($dir) && ! mkdir($dir, 0777, true) && ! is_dir($dir)) {
            self::fail('Could not create fixture dir: ' . $dir);
        }
        file_put_contents($path, $contents);
    }

    private function removeDirectory(string $dir): void
    {
        if ( ! is_dir($dir)) {
            return;
        }
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($dir, RecursiveDirectoryIterator::SKIP_DOTS),
            RecursiveIteratorIterator::CHILD_FIRST
        );
        foreach ($iterator as $item) {
            /** @var SplFileInfo $item */
            if ($item->isDir()) {
                // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_rmdir
                rmdir($item->getPathname());
            } else {
                // phpcs:ignore WordPress.WP.AlternativeFunctions.unlink_unlink
                unlink($item->getPathname());
            }
        }
        // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_rmdir
        rmdir($dir);
    }
}

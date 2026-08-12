<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use SplFileInfo;

/**
 * R5G-BR-05 / [rg-016]: production consumers of WordPress-style non-PSR-4
 * classes (living in class-*.php / interface-*.php files) must carry an
 * explicit require_once. The PHPUnit kebab-case fallback autoloader masks a
 * missing require for single-class files (suite stays green while WordPress
 * fatals on a stale classmap). DescriptionWriteStatus lives in its own
 * class-description-write-status.php (R17-BR-10) so consumers can address it
 * without freeriding the AltTextWriteStatus file.
 *
 * ## R19-BR-24 — predicate settlement (do not "fix" by auto-expanding)
 *
 * A naive scan of every type declared in class-*.php / interface-*.php against
 * every consumer that mentions it without a local require_once yields on the
 * order of ~100+ mismatches across dozens of files. That is the wrong
 * predicate for this project. Empirically (fresh PHP, AltContext classmap
 * stripped):
 *
 *   (B) holds for the bulk of those hits. Types are reached through the
 *   plugin bootstrap require block (alt-context.php) and entrypoint
 *   require_once chains (Api / RecognitionController / DescribeController /
 *   cluster-mutations-controller, etc.). Per-consumer require_once of every
 *   referenced WP-style type is not how this tree loads.
 *
 * Example bootstrap freeride (must stay green under the correct predicate):
 * DashboardPage extends AbstractSpaPage with no local require_once;
 * alt-context.php require_once's class-abstract-spa-page.php before the page.
 *
 * Real residual declaration-time freerides (defining file missing its own
 * extends/implements/use-trait require) still exist under a cold classmap
 * (e.g. mappers vs MapsResponseFields, repositories vs their interfaces).
 * Those are defining-file / chain-completeness bugs — not proof that every
 * consumer must re-require every type it names. Repair is out of this lane.
 *
 * Class list: hand-maintained allowlist in classChecks() of four *static
 * surface* types (RecognitionTransport, LoopbackHost, AltTextWriteStatus,
 * DescriptionWriteStatus) whose call sites freeride dangerously on classmap.
 * New class-*.php types are NOT auto-discovered — extend classChecks() only
 * when a type has the same static-call / multi-class-file risk profile.
 *
 * Declaration-time self-sufficiency for a secondary entrypoint is pinned
 * elsewhere (DescribeControllerAutoloadTest history-first probe, R20-BR-09).
 *
 * Self-exemption compares the src-relative path for exact equality so a
 * spoofed filename ending in class-recognition-transport.php cannot opt out.
 *
 * Satisfaction: only a real T_REQUIRE_ONCE statement whose expression names
 * the defining basename counts. A plain `require` (T_REQUIRE), a comment
 * mentioning require_once, or a string-only mention of the path do NOT
 * satisfy the guard.
 *
 * Reference detection is token-scoped (R16-BR-01): comments, docblocks, and
 * substring class names (NotRecognitionTransport) do not count. Forms
 * detected (R19-BR-10 / R16-BR-12 / R18-BR-04):
 *   - Static call / ::class: T_STRING short name followed by T_DOUBLE_COLON
 *   - FQCN identifier / use import: T_NAME_QUALIFIED / T_NAME_FULLY_QUALIFIED
 *   - Group-use import: use Ns\{Short, Other} (short name inside braces whose
 *     Ns\Short equals the FQCN)
 *   - Class-name string (callable-array / string class ref):
 *     T_CONSTANT_ENCAPSED_STRING whose unquoted value equals the FQCN
 *   - Heredoc / nowdoc body: T_ENCAPSED_AND_WHITESPACE containing the FQCN
 *
 * Not detected (accepted boundaries — do not rely on this guard for them):
 *   - `new Short(...)`, `instanceof Short`, `extends Short`, `implements Short`
 *   - Same-namespace / imported parameter, property, return, or catch typehints
 *   - Dynamically assembled FQCNs (`'AltContext\\Support\\' . 'RecognitionTransport'`)
 *   - Variable class names with no literal FQCN in the file
 *   - Reflection-only indirection
 * Those still need a human review path; the `::` / FQCN / group-use / string
 * forms cover every call site in src/ today for the allowlisted classes.
 *
 * Pin fixtures are staged under an injectable temp scan root — never under
 * the shipped src/ tree (R17-BR-07).
 *
 * @coversNothing
 */
class RecognitionTransportRequireOnceGuardTest extends TestCase
{
    /**
     * Temp fixtures written under the pin scan root; unlinked in tearDown.
     *
     * @var list<string>
     */
    private array $tempFixtures = [];

    /**
     * Isolated directory used by pin tests. Null for the baseline scan of real src/.
     */
    private ?string $pinScanRoot = null;

    protected function setUp(): void
    {
        parent::setUp();
        // Self-heal residue from interrupted prior runs (legacy src/ staging
        // path + any leftover pin-scan temp roots we can still reach).
        $this->purgeLegacySrcFixtures();
    }

    protected function tearDown(): void
    {
        foreach ($this->tempFixtures as $path) {
            if (is_file($path)) {
                // phpcs:ignore WordPress.WP.AlternativeFunctions.unlink_unlink -- test fixture cleanup
                unlink($path);
            }
        }
        $this->tempFixtures = [];

        if (is_string($this->pinScanRoot) && is_dir($this->pinScanRoot)) {
            $this->removeDirectory($this->pinScanRoot);
        }
        $this->pinScanRoot = null;

        // Belt-and-braces: never leave residue in the shipped tree.
        $this->purgeLegacySrcFixtures();

        parent::tearDown();
    }

    /**
     * Every src/ file that references a guarded class (static `::`, FQCN
     * identifier, group-use, or class-name string / callable array) must also
     * require the defining file.
     *
     * @return array<string, array{require: string, short: string, fqcn: string}>
     */
    private static function classChecks(): array
    {
        return [
            'RecognitionTransport' => [
                'require' => 'support/class-recognition-transport.php',
                'short' => 'RecognitionTransport',
                'fqcn' => 'AltContext\\Support\\RecognitionTransport',
            ],
            'LoopbackHost' => [
                'require' => 'support/class-loopback-host.php',
                'short' => 'LoopbackHost',
                'fqcn' => 'AltContext\\Support\\LoopbackHost',
            ],
            // R17-BR-08 / R17-BR-10: independently file-addressable status surfaces.
            'AltTextWriteStatus' => [
                'require' => 'api/class-alt-text-write-status.php',
                'short' => 'AltTextWriteStatus',
                'fqcn' => 'AltContext\\Api\\AltTextWriteStatus',
            ],
            'DescriptionWriteStatus' => [
                'require' => 'api/class-description-write-status.php',
                'short' => 'DescriptionWriteStatus',
                'fqcn' => 'AltContext\\Api\\DescriptionWriteStatus',
            ],
        ];
    }

    public function testConsumersExplicitlyRequireTransportAndLoopbackHost(): void
    {
        $offenders = $this->collectOffenders();
        $this->assertSame(
            [],
            $offenders,
            "src/ consumers must explicitly require_once guarded class files:\n"
            . implode("\n", $offenders)
        );
    }

    /**
     * R19-BR-24: classChecks() stays a hand-maintained static-surface allowlist.
     * Auto-expanding it to every class-*.php type reintroduces ~100+ false
     * positives against bootstrap/entrypoint reachability.
     */
    public function testClassChecksAllowlistIsNotAutoExpandedToAllWpStyleTypes(): void
    {
        $this->assertSame(
            [
                'RecognitionTransport',
                'LoopbackHost',
                'AltTextWriteStatus',
                'DescriptionWriteStatus',
            ],
            array_keys(self::classChecks()),
            'Do not auto-discover every class-*.php type into classChecks(); that is the wrong [rg-016] predicate (R19-BR-24)'
        );
    }

    /**
     * R19-BR-24: bootstrap-reachable freeride must not be a finding under the
     * correct predicate. DashboardPage extends AbstractSpaPage without a local
     * require_once; alt-context.php loads abstract before the page. A naive
     * per-consumer scan would flag this; the allowlist guard must not.
     */
    public function testBootstrapReachableAdminSpaPageIsNotAGuardFinding(): void
    {
        $pluginRoot = dirname(__DIR__, 2);
        $dashboard = (string) file_get_contents($pluginRoot . '/src/admin/class-dashboard-page.php');
        $entrypoint = (string) file_get_contents($pluginRoot . '/alt-context.php');

        $this->assertMatchesRegularExpression(
            '/class\s+DashboardPage\s+extends\s+AbstractSpaPage\b/',
            $dashboard,
            'DashboardPage must still extend AbstractSpaPage for this freeride pin'
        );
        $this->assertFalse(
            $this->containsRequireOnceFor($dashboard, 'class-abstract-spa-page.php'),
            'DashboardPage deliberately freerides on the bootstrap require order'
        );

        $abstractPos = strpos($entrypoint, "src/admin/class-abstract-spa-page.php");
        $dashboardPos = strpos($entrypoint, "src/admin/class-dashboard-page.php");
        $this->assertNotFalse($abstractPos, 'bootstrap must require abstract spa page');
        $this->assertNotFalse($dashboardPos, 'bootstrap must require dashboard page');
        $this->assertLessThan(
            $dashboardPos,
            $abstractPos,
            'bootstrap must load AbstractSpaPage before DashboardPage'
        );

        // Fresh process, no AltContext classmap: alone fails, bootstrap order works.
        $alone = $this->freshLoadWithoutAltContextClassmap(
            [$pluginRoot . '/src/admin/class-dashboard-page.php']
        );
        $this->assertStringContainsString(
            'AbstractSpaPage',
            $alone,
            'isolation load must fail without AbstractSpaPage (proves freeride, not self-sufficiency)'
        );

        $ordered = $this->freshLoadWithoutAltContextClassmap(
            [
                $pluginRoot . '/src/admin/class-abstract-spa-page.php',
                $pluginRoot . '/src/admin/class-dashboard-page.php',
            ]
        );
        $this->assertSame(
            'OK',
            trim($ordered),
            'bootstrap order must load DashboardPage without classmap; got: ' . var_export($ordered, true)
        );

        $this->assertSame(
            [],
            $this->collectOffenders(),
            'allowlist guard must stay green on bootstrap freerides'
        );
    }

    /**
     * R19-BR-24: a naive full-tree per-consumer scan is large; the real guard
     * (allowlist) produces zero findings on the same tree.
     */
    public function testNaivePerConsumerScanIsMassiveWhileAllowlistGuardStaysGreen(): void
    {
        $naiveCount = $this->countNaiveWpStylePerConsumerMismatches();
        $this->assertGreaterThan(
            50,
            $naiveCount,
            'Expected a large naive per-consumer mismatch count (bootstrap/entrypoint freerides). '
            . 'If this collapses near zero, re-check the scan or the load model.'
        );
        $this->assertSame(
            [],
            $this->collectOffenders(),
            "Allowlist guard must report no offenders despite naive count={$naiveCount}"
        );
    }

    /**
     * R16-BR-01: a comment-only mention of RecognitionTransport:: must not
     * trip the guard (raw str_contains previously did).
     */
    public function testCommentOnlyShortNameDoesNotTriggerGuard(): void
    {
        $relative = 'api/_acx_guard_fixture_comment_short.php';
        $this->writePinFixture(
            $relative,
            "<?php\n// RecognitionTransport:: is mentioned only in a comment here.\n"
            . "namespace AltContext\\Api;\nclass ProbeCommentOnlyShort {}\n"
        );

        $offenders = $this->collectOffenders($this->pinScanRoot());
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders,
            'Comment-only RecognitionTransport:: must not count as a reference'
        );
        $this->assertSame([], $offenders, 'Fixture must not introduce any offenders');
    }

    /**
     * R16-BR-01: a comment-only FQCN must not trip the guard.
     */
    public function testCommentOnlyFqcnDoesNotTriggerGuard(): void
    {
        $relative = 'api/_acx_guard_fixture_comment_fqcn.php';
        $this->writePinFixture(
            $relative,
            "<?php\n// AltContext\\Support\\RecognitionTransport mentioned only in a comment.\n"
            . "namespace AltContext\\Api;\nclass ProbeCommentOnlyFqcn {}\n"
        );

        $offenders = $this->collectOffenders($this->pinScanRoot());
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders,
            'Comment-only FQCN must not count as a reference'
        );
        $this->assertSame([], $offenders, 'Fixture must not introduce any offenders');
    }

    /**
     * R16-BR-01: substring class names must not match the short name.
     */
    public function testSubstringClassNameDoesNotTriggerGuard(): void
    {
        $relative = 'api/_acx_guard_fixture_substring.php';
        $this->writePinFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "class NotRecognitionTransport { public static function x(): void {} }\n"
            . "NotRecognitionTransport::x();\n"
        );

        $offenders = $this->collectOffenders($this->pinScanRoot());
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders,
            'NotRecognitionTransport:: must not match RecognitionTransport'
        );
        $this->assertSame([], $offenders, 'Fixture must not introduce any offenders');
    }

    /**
     * R16-BR-01: a real static call without require_once must still fail.
     */
    public function testRealStaticCallWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_real_call.php';
        $this->writePinFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "class ProbeRealCall {\n"
            . "    public function run(): void { RecognitionTransport::get('http://x'); }\n"
            . "}\n"
        );

        $expected = sprintf(
            '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
            $relative
        );
        $this->assertContains(
            $expected,
            $this->collectOffenders($this->pinScanRoot()),
            'Real RecognitionTransport::get() without require_once must fail the guard'
        );
    }

    /**
     * Real use-import plus require_once stays green.
     */
    public function testRealUseWithRequireOnceIsGreen(): void
    {
        $relative = 'api/_acx_guard_fixture_use_ok.php';
        $this->writePinFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "require_once __DIR__ . '/../support/class-recognition-transport.php';\n"
            . "use AltContext\\Support\\RecognitionTransport;\n"
            . "class ProbeUseOk {\n"
            . "    public function run(): void { RecognitionTransport::get('http://x'); }\n"
            . "}\n"
        );

        $offenders = $this->collectOffenders($this->pinScanRoot());
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders
        );
        $this->assertSame([], $offenders, 'Valid consumer with require_once must stay green');
    }

    /**
     * R16-BR-12: heredoc body carrying the FQCN is a real reference.
     */
    public function testHeredocFqcnWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_heredoc.php';
        $this->writePinFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "class ProbeHeredoc {\n"
            . "    public function cname(): string {\n"
            . "        return <<<EOT\n"
            . "AltContext\\Support\\RecognitionTransport\n"
            . "EOT;\n"
            . "    }\n"
            . "}\n"
        );

        $expected = sprintf(
            '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
            $relative
        );
        $this->assertContains($expected, $this->collectOffenders($this->pinScanRoot()));
    }

    /**
     * R16-BR-12: double-quoted FQCN with single backslashes must match after
     * unquote (PHP keeps \S for unrecognised escapes — same runtime value as \\).
     */
    public function testDoubleQuotedSingleBackslashFqcnWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_dq_single_bs.php';
        // Build source so the file literally contains single-backslash sequences
        // inside a double-quoted string: "AltContext\Support\RecognitionTransport"
        $php = '<?php' . "\n" . 'namespace AltContext\\Api;' . "\n"
            . 'class ProbeDq {' . "\n"
            . '    public function cname(): string {' . "\n"
            . '        return "AltContext\\Support\\RecognitionTransport";' . "\n"
            . '    }' . "\n"
            . '}' . "\n";
        $this->writePinFixture($relative, $php);

        // Pin unquote semantics deliberately: both single- and double-bs source
        // forms unquote to the FQCN (PHP double-quote rules).
        $this->assertSame(
            'AltContext\\Support\\RecognitionTransport',
            $this->unquoteString('"AltContext\\Support\\RecognitionTransport"'),
            'single-bs double-quoted: unrecognised \\S keeps both chars'
        );
        $this->assertSame(
            'AltContext\\Support\\RecognitionTransport',
            $this->unquoteString('"AltContext\\\\Support\\\\RecognitionTransport"'),
            'double-bs double-quoted: \\\\ collapses to \\'
        );
        $this->assertSame(
            $this->unquoteString('"AltContext\\Support\\RecognitionTransport"'),
            $this->unquoteString('"AltContext\\\\Support\\\\RecognitionTransport"'),
            '"A\\Support" and "A\\\\Support" unquote to the same FQCN string'
        );

        $expected = sprintf(
            '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
            $relative
        );
        $this->assertContains($expected, $this->collectOffenders($this->pinScanRoot()));
    }

    /**
     * R18-BR-04: group-use imports (use Ns\{A, B}) without require_once must fail.
     */
    public function testGroupUseWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_group_use.php';
        $this->writePinFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "use AltContext\\Support\\{LoopbackHost, RecognitionTransport};\n"
            . "class ProbeGroupUse {}\n"
        );

        $offenders = $this->collectOffenders($this->pinScanRoot());
        $this->assertContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders,
            'Group-use RecognitionTransport without require_once must fail the guard'
        );
        $this->assertContains(
            sprintf(
                '%s references LoopbackHost but has no require_once for class-loopback-host.php',
                $relative
            ),
            $offenders,
            'Group-use LoopbackHost without require_once must fail the guard'
        );
    }

    /**
     * R17-BR-08: AltTextWriteStatus consumer without require_once is detected.
     */
    public function testAltTextWriteStatusWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_alt_status.php';
        $this->writePinFixture(
            $relative,
            "<?php\nnamespace AltContext\\Cli;\n"
            . "use AltContext\\Api\\AltTextWriteStatus;\n"
            . "class ProbeAltStatus {\n"
            . "    public function s(): string { return AltTextWriteStatus::FAILED; }\n"
            . "}\n"
        );

        $expected = sprintf(
            '%s references AltTextWriteStatus but has no require_once for class-alt-text-write-status.php',
            $relative
        );
        $this->assertContains(
            $expected,
            $this->collectOffenders($this->pinScanRoot()),
            'AltTextWriteStatus:: without require_once must fail the guard'
        );
    }

    /**
     * R17-BR-08 / R17-BR-10: DescriptionWriteStatus is guarded at its own file.
     */
    public function testDescriptionWriteStatusWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_desc_status.php';
        $this->writePinFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api\\Services;\n"
            . "use AltContext\\Api\\DescriptionWriteStatus;\n"
            . "class ProbeDescStatus {\n"
            . "    public function s(): string { return DescriptionWriteStatus::FAILED; }\n"
            . "}\n"
        );

        $expected = sprintf(
            '%s references DescriptionWriteStatus but has no require_once for class-description-write-status.php',
            $relative
        );
        $this->assertContains(
            $expected,
            $this->collectOffenders($this->pinScanRoot()),
            'DescriptionWriteStatus:: without require_once must fail the guard'
        );
    }

    /**
     * R17-BR-07: pin fixtures must never land in the shipped src/ tree.
     */
    public function testPinFixturesAreNotWrittenIntoShippedSrcTree(): void
    {
        $relative = 'api/_acx_guard_fixture_isolation.php';
        $this->writePinFixture(
            $relative,
            "<?php\n// isolation probe — must not appear under shipped src/\n"
        );

        $shipped = dirname(__DIR__, 2) . '/src/' . $relative;
        $this->assertFileDoesNotExist(
            $shipped,
            'Pin fixtures must not be written into the shipped src/ tree'
        );
        $this->assertFileExists(
            $this->pinScanRoot() . '/' . $relative,
            'Pin fixture must exist under the isolated scan root'
        );

        $legacy = $this->listLegacySrcFixtures();
        $this->assertSame(
            [],
            $legacy,
            'No _acx_guard_fixture_* residue under shipped src/: ' . implode(', ', $legacy)
        );
    }

    /**
     * @param string|null $scanRoot When null, scan real src/. Pin tests pass the
     *                              isolated temp root so fixtures never touch shipped tree.
     * @return list<string>
     */
    private function collectOffenders(?string $scanRoot = null): array
    {
        if (null === $scanRoot) {
            $resolved = realpath(dirname(__DIR__, 2) . '/src');
            $this->assertIsString($resolved, 'src/ must exist');
        } else {
            $resolved = realpath($scanRoot);
            $this->assertIsString($resolved, 'pin scan root must exist');
        }

        $offenders = [];

        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($resolved, RecursiveDirectoryIterator::SKIP_DOTS)
        );

        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if (!$file->isFile() || 'php' !== $file->getExtension()) {
                continue;
            }

            $path = $file->getPathname();
            $contents = (string) file_get_contents($path);
            $relative = str_replace('\\', '/', substr($path, strlen($resolved) + 1));

            foreach (self::classChecks() as $label => $check) {
                if (!$this->fileReferencesClass($contents, $check['short'], $check['fqcn'])) {
                    continue;
                }

                // The defining file itself need not re-require its own class
                // file, but RecognitionTransport must still require LoopbackHost
                // (caught by the LoopbackHost check on that file).
                // Exact src-relative path equality — not a suffix match — so
                // evil-class-recognition-transport.php cannot self-exempt.
                if ($relative === $check['require']) {
                    continue;
                }

                $requireFile = basename($check['require']);
                if (!$this->containsRequireOnceFor($contents, $requireFile)) {
                    $offenders[] = sprintf(
                        '%s references %s but has no require_once for %s',
                        $relative,
                        $label,
                        $requireFile
                    );
                }
            }
        }

        return $offenders;
    }

    /**
     * Isolated temp root for pin fixtures (R17-BR-07). Outside the repo so
     * residue is unstageable by git and never packaged with the plugin.
     */
    private function pinScanRoot(): string
    {
        if (null === $this->pinScanRoot) {
            $dir = sys_get_temp_dir() . '/acx_require_once_guard_' . str_replace('.', '', uniqid('', true));
            // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_mkdir -- test fixture root
            mkdir($dir, 0700, true);
            $this->pinScanRoot = $dir;
        }

        return $this->pinScanRoot;
    }

    private function writePinFixture(string $relative, string $contents): void
    {
        $root = $this->pinScanRoot();
        $path = $root . '/' . $relative;
        $dir = dirname($path);
        if (!is_dir($dir)) {
            // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_mkdir -- test fixture dir
            mkdir($dir, 0700, true);
        }
        // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_file_put_contents -- test fixture
        file_put_contents($path, $contents);
        $this->tempFixtures[] = $path;
    }

    /**
     * Remove any leftover _acx_guard_fixture_* under shipped src/ (legacy path).
     */
    private function purgeLegacySrcFixtures(): void
    {
        foreach ($this->listLegacySrcFixtures() as $path) {
            if (is_file($path)) {
                // phpcs:ignore WordPress.WP.AlternativeFunctions.unlink_unlink -- legacy residue cleanup
                unlink($path);
            }
        }
    }

    /**
     * @return list<string>
     */
    private function listLegacySrcFixtures(): array
    {
        $srcRoot = realpath(dirname(__DIR__, 2) . '/src');
        if (!is_string($srcRoot)) {
            return [];
        }

        $found = [];
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($srcRoot, RecursiveDirectoryIterator::SKIP_DOTS)
        );
        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if ($file->isFile() && str_starts_with($file->getFilename(), '_acx_guard_fixture_')) {
                $found[] = $file->getPathname();
            }
        }

        return $found;
    }

    private function removeDirectory(string $dir): void
    {
        if (!is_dir($dir)) {
            return;
        }
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($dir, RecursiveDirectoryIterator::SKIP_DOTS),
            RecursiveIteratorIterator::CHILD_FIRST
        );
        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if ($file->isDir()) {
                // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_rmdir -- test fixture cleanup
                rmdir($file->getPathname());
            } elseif ($file->isFile()) {
                // phpcs:ignore WordPress.WP.AlternativeFunctions.unlink_unlink -- test fixture cleanup
                unlink($file->getPathname());
            }
        }
        // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_rmdir -- test fixture cleanup
        rmdir($dir);
    }

    /**
     * True when $contents references the class via token-scoped static `::`,
     * FQCN name token / use-import, group-use short name, class-name string,
     * or heredoc/nowdoc body. Comments and substring identifiers are ignored
     * (R16-BR-01).
     */
    private function fileReferencesClass(string $contents, string $short, string $fqcn): bool
    {
        $tokens = token_get_all($contents);
        $count = count($tokens);
        $fqcnFullyQualified = '\\' . $fqcn;

        for ($i = 0; $i < $count; $i++) {
            $token = $tokens[$i];
            if (!is_array($token)) {
                continue;
            }

            [$id, $text] = $token;

            // Skip comments entirely — they must never count as references.
            if (T_COMMENT === $id || T_DOC_COMMENT === $id) {
                continue;
            }

            // Group-use: use Ns\{Short, Other} (R18-BR-04).
            if (T_USE === $id) {
                if ($this->groupUseReferencesClass($tokens, $i, $short, $fqcn)) {
                    return true;
                }
                continue;
            }

            // Static call / ::class: exact T_STRING short name + T_DOUBLE_COLON.
            // NotRecognitionTransport / XRecognitionTransport do not match.
            if (T_STRING === $id && $text === $short) {
                $next = $this->nextSignificantToken($tokens, $i);
                if (is_array($next) && T_DOUBLE_COLON === $next[0]) {
                    return true;
                }
                continue;
            }

            // FQCN identifier or use-import (PHP 8+ name tokens).
            if (
                (defined('T_NAME_QUALIFIED') && T_NAME_QUALIFIED === $id && $text === $fqcn)
                || (defined('T_NAME_FULLY_QUALIFIED') && T_NAME_FULLY_QUALIFIED === $id
                    && ($text === $fqcnFullyQualified || $text === $fqcn))
            ) {
                return true;
            }

            // Class-name strings / callable arrays.
            if (T_CONSTANT_ENCAPSED_STRING === $id) {
                if ($this->unquoteString($text) === $fqcn) {
                    return true;
                }
                continue;
            }

            // Heredoc / nowdoc bodies (R16-BR-12): arrive as T_ENCAPSED_AND_WHITESPACE.
            if (T_ENCAPSED_AND_WHITESPACE === $id) {
                if ($this->heredocBodyReferencesFqcn($text, $fqcn)) {
                    return true;
                }
            }
        }

        return false;
    }

    /**
     * Detect group-use imports: use Namespace\{Short, Other}.
     * Tokens: T_USE, T_NAME_QUALIFIED ns, T_NS_SEPARATOR, '{', T_STRING names...
     *
     * @param array<int, string|array{0:int,1:string,2:int}> $tokens
     */
    private function groupUseReferencesClass(array $tokens, int $useIndex, string $short, string $fqcn): bool
    {
        $count = count($tokens);
        $j = $useIndex + 1;

        while ($j < $count && is_array($tokens[$j])
            && in_array($tokens[$j][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)
        ) {
            $j++;
        }

        // use function / use const — not a class import.
        if (
            $j < $count && is_array($tokens[$j])
            && in_array($tokens[$j][0], [T_FUNCTION, T_CONST], true)
        ) {
            return false;
        }

        // Collect namespace prefix until '{' (group) or ';' / ',' (not group).
        $ns = '';
        $foundBrace = false;
        for (; $j < $count; $j++) {
            $t = $tokens[$j];
            if ('{' === $t) {
                $foundBrace = true;
                $j++;
                break;
            }
            if (';' === $t || ',' === $t) {
                return false;
            }
            if (is_array($t)) {
                if (in_array($t[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
                    continue;
                }
                if (
                    in_array(
                        $t[0],
                        [T_STRING, T_NAME_QUALIFIED, T_NAME_FULLY_QUALIFIED, T_NS_SEPARATOR],
                        true
                    )
                ) {
                    $ns .= $t[1];
                    continue;
                }

                return false;
            }

            return false;
        }

        if (!$foundBrace) {
            return false;
        }

        $ns = rtrim($ns, '\\');

        // Parse imported names inside braces until '}'.
        $current = '';
        $sawAs = false;
        for (; $j < $count; $j++) {
            $t = $tokens[$j];
            if ('}' === $t) {
                return $this->groupUseNameMatches($ns, $current, $fqcn);
            }
            if (',' === $t) {
                if ($this->groupUseNameMatches($ns, $current, $fqcn)) {
                    return true;
                }
                $current = '';
                $sawAs = false;
                continue;
            }
            if (is_array($t)) {
                if (in_array($t[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
                    continue;
                }
                if (T_AS === $t[0]) {
                    // use Ns\{Foo as Bar} — Foo is the referenced class; stop appending.
                    $sawAs = true;
                    continue;
                }
                if ($sawAs) {
                    // Skip alias identifier.
                    continue;
                }
                if (
                    in_array(
                        $t[0],
                        [T_STRING, T_NAME_QUALIFIED, T_NAME_FULLY_QUALIFIED, T_NS_SEPARATOR],
                        true
                    )
                ) {
                    $current .= $t[1];
                    continue;
                }
            }
        }

        return false;
    }

    private function groupUseNameMatches(string $ns, string $name, string $fqcn): bool
    {
        $name = trim($name);
        if ('' === $name) {
            return false;
        }
        $name = ltrim($name, '\\');

        return ($ns . '\\' . $name) === $fqcn;
    }

    /**
     * Heredoc/nowdoc body matches when it is (or contains as a whole line) the FQCN.
     */
    private function heredocBodyReferencesFqcn(string $body, string $fqcn): bool
    {
        if (trim($body) === $fqcn) {
            return true;
        }

        // Multi-line bodies: any full line equal to the FQCN.
        $lines = preg_split('/\R/', $body);
        if (!is_array($lines)) {
            return false;
        }
        foreach ($lines as $line) {
            if ($line === $fqcn) {
                return true;
            }
        }

        return false;
    }

    /**
     * Next non-whitespace, non-comment token after $index, or null.
     *
     * @param array<int, string|array{0:int,1:string,2:int}> $tokens
     * @return string|array{0:int,1:string,2:int}|null
     */
    private function nextSignificantToken(array $tokens, int $index)
    {
        $count = count($tokens);
        for ($j = $index + 1; $j < $count; $j++) {
            $t = $tokens[$j];
            if (!is_array($t)) {
                return $t;
            }
            if (in_array($t[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
                continue;
            }

            return $t;
        }

        return null;
    }

    /**
     * Recover the runtime string value from a T_CONSTANT_ENCAPSED_STRING token.
     *
     * Double-quoted deliberate rule (R16-BR-12): PHP retains both the backslash
     * and the following character for unrecognised escape sequences. Therefore
     * `"A\Support"` and `"A\\Support"` both unquote to `A\Support` (the FQCN
     * form). `stripcslashes` is wrong — it collapses `\S` → `S`.
     */
    private function unquoteString(string $text): string
    {
        if (strlen($text) < 2) {
            return $text;
        }

        $quote = $text[0];
        if (("'" === $quote || '"' === $quote) && $text[strlen($text) - 1] === $quote) {
            $inner = substr($text, 1, -1);
            if ("'" === $quote) {
                // Single-quoted: only \\ and \' are escapes.
                return str_replace(["\\\\", "\\'"], ["\\", "'"], $inner);
            }

            return $this->unquoteDoubleQuotedInner($inner);
        }

        return $text;
    }

    /**
     * Unescape a double-quoted string body per PHP runtime rules (subset needed
     * for class FQCNs, plus the common special escapes).
     */
    private function unquoteDoubleQuotedInner(string $inner): string
    {
        $result = '';
        $len = strlen($inner);
        for ($i = 0; $i < $len; $i++) {
            if ('\\' !== $inner[$i] || $i + 1 >= $len) {
                $result .= $inner[$i];
                continue;
            }

            $next = $inner[$i + 1];
            switch ($next) {
                case '\\':
                case '"':
                case '$':
                    $result .= $next;
                    $i++;
                    break;
                case 'n':
                    $result .= "\n";
                    $i++;
                    break;
                case 'r':
                    $result .= "\r";
                    $i++;
                    break;
                case 't':
                    $result .= "\t";
                    $i++;
                    break;
                case 'v':
                    $result .= "\v";
                    $i++;
                    break;
                case 'e':
                    $result .= "\e";
                    $i++;
                    break;
                case 'f':
                    $result .= "\f";
                    $i++;
                    break;
                default:
                    // Unrecognised escape: keep both backslash and character
                    // (PHP: "\S" === "\\S" for non-special S).
                    $result .= '\\' . $next;
                    $i++;
                    break;
            }
        }

        return $result;
    }

    /**
     * True when a real T_REQUIRE_ONCE statement names $requireFile.
     * Comments and string-only mentions do not count.
     */
    private function containsRequireOnceFor(string $contents, string $requireFile): bool
    {
        $tokens = token_get_all($contents);
        $count = count($tokens);

        for ($i = 0; $i < $count; $i++) {
            $token = $tokens[$i];
            if (!is_array($token) || T_REQUIRE_ONCE !== $token[0]) {
                continue;
            }

            // Collect the require_once expression until ';' — comments skipped.
            $stmt = '';
            for ($j = $i + 1; $j < $count; $j++) {
                $t = $tokens[$j];
                if (';' === $t) {
                    break;
                }
                if (is_array($t)) {
                    if (in_array($t[0], [T_COMMENT, T_DOC_COMMENT], true)) {
                        continue;
                    }
                    $stmt .= $t[1];
                } else {
                    $stmt .= $t;
                }
            }

            if (str_contains($stmt, $requireFile)) {
                return true;
            }
        }

        return false;
    }

    /**
     * Fresh process: Composer without AltContext classmap/PSR-4, then require
     * the given absolute paths in order. Returns "OK" or the process output.
     *
     * @param list<string> $absolutePaths
     */
    private function freshLoadWithoutAltContextClassmap(array $absolutePaths): string
    {
        $pluginRoot = dirname(__DIR__, 2);
        $requires = '';
        foreach ($absolutePaths as $path) {
            $requires .= 'require_once ' . var_export($path, true) . ";\n";
        }

        $script = <<<'PHP'
<?php
$root = $argv[1];
require_once $root . '/vendor/composer/ClassLoader.php';
$loader = new Composer\Autoload\ClassLoader();
$psr4 = require $root . '/vendor/composer/autoload_psr4.php';
foreach ($psr4 as $prefix => $paths) {
	if (str_starts_with($prefix, 'AltContext\\')) {
		continue;
	}
	$loader->setPsr4($prefix, $paths);
}
$classmap = require $root . '/vendor/composer/autoload_classmap.php';
$filtered = array();
foreach ($classmap as $class => $path) {
	if (str_starts_with($class, 'AltContext\\')) {
		continue;
	}
	$filtered[$class] = $path;
}
$loader->addClassMap($filtered);
$loader->register(true);
foreach (require $root . '/vendor/composer/autoload_files.php' as $file) {
	require $file;
}
try {
REQUIRES
	echo "OK\n";
} catch (Throwable $e) {
	echo $e->getMessage() . "\n";
}
PHP;
        $script = str_replace('REQUIRES', $requires, $script);

        $tmp = tempnam(sys_get_temp_dir(), 'acx_rg016_');
        $this->assertIsString($tmp);
        // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_file_put_contents -- test probe script
        file_put_contents($tmp, $script);
        $output = (string) shell_exec(
            sprintf('php %s %s 2>&1', escapeshellarg($tmp), escapeshellarg($pluginRoot))
        );
        // phpcs:ignore WordPress.WP.AlternativeFunctions.unlink_unlink -- test probe cleanup
        unlink($tmp);

        return $output;
    }

    /**
     * Count naive (consumer references WP-style type without local require_once)
     * mismatches. Used only to prove that volume is large under the wrong
     * predicate — not as the production guard.
     */
    private function countNaiveWpStylePerConsumerMismatches(): int
    {
        $srcRoot = realpath(dirname(__DIR__, 2) . '/src');
        $this->assertIsString($srcRoot);

        $defs = [];
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($srcRoot, RecursiveDirectoryIterator::SKIP_DOTS)
        );
        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if (!$file->isFile() || 'php' !== $file->getExtension()) {
                continue;
            }
            $base = $file->getFilename();
            if (!preg_match('/^(class|interface|trait)-.+\.php$/', $base)) {
                continue;
            }
            $contents = (string) file_get_contents($file->getPathname());
            $relative = str_replace('\\', '/', substr($file->getPathname(), strlen($srcRoot) + 1));
            if (!preg_match('/namespace\s+([^;]+);/', $contents, $nsMatch)) {
                continue;
            }
            $ns = trim($nsMatch[1]);
            if (
                !preg_match_all(
                    '/^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+([A-Za-z_][A-Za-z0-9_]*)/m',
                    $contents,
                    $typeMatches
                )
            ) {
                continue;
            }
            foreach ($typeMatches[1] as $short) {
                $defs[ $ns . '\\' . $short ] = [
                    'file' => $relative,
                    'base' => $base,
                    'short' => $short,
                    'fqcn' => $ns . '\\' . $short,
                ];
            }
        }

        $count = 0;
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($srcRoot, RecursiveDirectoryIterator::SKIP_DOTS)
        );
        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if (!$file->isFile() || 'php' !== $file->getExtension()) {
                continue;
            }
            $contents = (string) file_get_contents($file->getPathname());
            $relative = str_replace('\\', '/', substr($file->getPathname(), strlen($srcRoot) + 1));
            foreach ($defs as $check) {
                if ($relative === $check['file']) {
                    continue;
                }
                if (!$this->fileReferencesClass($contents, $check['short'], $check['fqcn'])) {
                    continue;
                }
                if (!$this->containsRequireOnceFor($contents, $check['base'])) {
                    ++$count;
                }
            }
        }

        return $count;
    }
}

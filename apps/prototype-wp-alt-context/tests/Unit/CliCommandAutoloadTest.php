<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * R20-BR-26: all six WP-CLI command entry files must be require_once'd in the
 * alt-context.php WP_CLI block so a stale Composer classmap cannot fatal
 * `acx_register_cli_commands()` with "Class not found".
 *
 * Discovery-only probe: stub WP_CLI_Command, require only the paths listed in
 * the production WP_CLI block (no Composer autoloader), assert every registered
 * command class declares.
 *
 * @coversNothing
 */
class CliCommandAutoloadTest extends TestCase
{
    /**
     * CLI command classes registered by acx_register_cli_commands().
     *
     * @var list<string>
     */
    private const CLI_COMMAND_CLASSES = [
        'AltContext\\Cli\\DescriptionCommand',
        'AltContext\\Cli\\DescriptionUsageCommand',
        'AltContext\\Cli\\MirrorIntegrityCommand',
        'AltContext\\Cli\\DescriptionRefreshCommand',
        'AltContext\\Cli\\XmpBackfillCommand',
        'AltContext\\Cli\\ResetProjectionCommand',
    ];

    /**
     * Require lines the WP_CLI block must carry (relative to ACX_PLUGIN_DIR).
     * Order matches alt-context.php: deps first, then the six command entries.
     *
     * @var list<string>
     */
    private const REQUIRED_CLI_ENTRYPOINT_PATHS = [
        'src/api/class-describe-controller.php',
        'src/api/services/class-description-candidate-service.php',
        'src/cli/class-description-command.php',
        'src/cli/class-description-usage-command.php',
        'src/cli/class-mirror-integrity-command.php',
        'src/cli/class-description-refresh-command.php',
        'src/cli/class-xmp-backfill-command.php',
        'src/cli/class-reset-projection-command.php',
    ];

    public function testEntrypointExplicitlyRequiresAllCliCommandFiles(): void
    {
        $entrypoint = realpath(__DIR__ . '/../../alt-context.php');
        self::assertIsString($entrypoint, 'alt-context.php must exist');

        $contents = (string) file_get_contents($entrypoint);

        foreach (self::REQUIRED_CLI_ENTRYPOINT_PATHS as $path) {
            $line = sprintf("require_once ACX_PLUGIN_DIR . '%s';", $path);
            $this->assertStringContainsString(
                $line,
                $contents,
                'alt-context.php WP_CLI block must explicitly require every CLI entry: ' . $line
            );
        }
    }

    public function testWpCliBlockLoadsAllSixCommandClassesWithoutComposerClassmap(): void
    {
        $pluginDir = realpath(__DIR__ . '/../..');
        self::assertIsString($pluginDir);

        $entrypoint = $pluginDir . '/alt-context.php';
        $contents = (string) file_get_contents($entrypoint);

        // Extract only the production WP_CLI require_once paths — the probe
        // freerides nothing; a missing require_once in the block must redden.
        if (!preg_match(
            "/if\s*\(\s*defined\s*\(\s*'WP_CLI'\s*\)\s*&&\s*WP_CLI\s*\)\s*\{(.*?)\n\}/s",
            $contents,
            $blockMatch
        )) {
            self::fail('Could not locate WP_CLI require block in alt-context.php');
        }

        // First WP_CLI block is the require block (the later one only add_action).
        preg_match_all(
            "/require_once\s+ACX_PLUGIN_DIR\s*\.\s*'([^']+)'\s*;/",
            $blockMatch[1],
            $pathMatches
        );
        $paths = $pathMatches[1];
        self::assertNotEmpty($paths, 'WP_CLI block must contain require_once lines');

        $requires = '';
        foreach ($paths as $path) {
            $requires .= sprintf("require_once %s;\n", var_export($pluginDir . '/' . $path, true));
        }

        $checks = '';
        foreach (self::CLI_COMMAND_CLASSES as $fqcn) {
            $checks .= sprintf(
                "if (!class_exists(%s, false)) { fwrite(STDERR, %s); exit(1); }\n",
                var_export($fqcn, true),
                var_export($fqcn . ' not loaded', true)
            );
        }

        $script = "<?php\n"
            . "if (!class_exists('WP_CLI_Command', false)) {\n"
            . "    class WP_CLI_Command {}\n"
            . "}\n"
            . $requires
            . $checks
            . "echo 'ok';\n";

        $tmp = tempnam(sys_get_temp_dir(), 'acx_cli_autoload_');
        self::assertIsString($tmp);
        file_put_contents($tmp, $script);
        $output = trim((string) shell_exec(sprintf('php %s 2>&1', escapeshellarg($tmp))));
        unlink($tmp);

        $this->assertSame(
            'ok',
            $output,
            'The WP_CLI require block must declare all six command classes with no Composer '
                . 'autoloader present; got: ' . var_export($output, true)
        );
    }
}

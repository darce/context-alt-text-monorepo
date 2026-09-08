<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\AbstractSpaPage;
use AltContext\Tests\TestCase;
use ReflectionClass;
use ReflectionMethod;

/**
 * BR-28..31: four admin page shells' getLoadingMessage() still used Don't-say
 * jargon (workbench/dashboard/roster/bare retention) after the wave-2
 * admin-menu rename — nothing gated PHP loading-message copy against
 * docs/ux/glossary.md, only the JS surfaces. This test enumerates every
 * concrete AbstractSpaPage subclass via glob + reflection (never a hardcoded
 * class list) so a newly added page is covered automatically, and sources
 * banned terms from the glossary at test time so there is one place to update.
 *
 * @covers \AltContext\Admin\AbstractSpaPage
 */
class LoadingMessageVocabularyTest extends TestCase
{
    /**
     * Parses docs/ux/glossary.md's Say/Don't-say table (same algorithm as the
     * TS counterpart in syncVocabulary.test.ts, BR-34) so this test and the JS
     * guard share one source of truth instead of two hand-typed vocab lists.
     *
     * @return list<array{say: string, dontSay: list<string>}>
     */
    private static function parseGlossaryRows(): array
    {
        $realPath = realpath(__DIR__ . '/../../../../docs/ux/glossary.md');
        self::assertIsString($realPath, 'docs/ux/glossary.md must exist at the repo root');

        $markdown = (string) file_get_contents($realPath);
        $rows = [];

        foreach (explode("\n", $markdown) as $line) {
            if (!str_starts_with(trim($line), '|')) {
                continue;
            }

            $cells = array_slice(array_map('trim', explode('|', $line)), 1, -1);
            if (count($cells) < 3 || $cells[0] === 'Concept' || preg_match('/^-+$/', $cells[1]) === 1) {
                continue;
            }

            $say = trim(str_replace('**', '', $cells[1]));
            $dontSay = array_values(array_filter(array_map('trim', explode(',', $cells[2]))));

            if ($say !== '' && $dontSay !== []) {
                $rows[] = ['say' => $say, 'dontSay' => $dontSay];
            }
        }

        return $rows;
    }

    /**
     * True (returns the matched term) if $text contains one of $row's bare
     * Don't-say terms. If a term is itself a substring of the Say phrase (e.g.
     * "Retention" inside "Data Retention"), legitimate Say-phrase occurrences
     * are masked out first so a correct destination name is never flagged
     * (the same masking used by the JS BR-34 guard).
     *
     * @param array{say: string, dontSay: list<string>} $row
     */
    private static function findDontSayHit(string $text, array $row): ?string
    {
        $lowerText = strtolower($text);
        $lowerSay = strtolower($row['say']);

        foreach ($row['dontSay'] as $term) {
            $lowerTerm = strtolower($term);
            $haystack = $lowerText;

            if (str_contains($lowerSay, $lowerTerm)) {
                $haystack = str_replace($lowerSay, str_repeat(' ', strlen($lowerSay)), $haystack);
            }

            if (str_contains($haystack, $lowerTerm)) {
                return $term;
            }
        }

        return null;
    }

    /**
     * Every concrete (non-abstract) AbstractSpaPage subclass under src/admin,
     * discovered by glob + reflection so a newly added page class is picked up
     * without editing this test.
     *
     * @return list<AbstractSpaPage>
     */
    private static function concreteSpaPages(): array
    {
        $adminDir = realpath(__DIR__ . '/../../src/admin');
        self::assertIsString($adminDir, 'src/admin must exist');

        foreach (glob($adminDir . '/class-*.php') ?: [] as $file) {
            require_once $file;
        }

        $pages = [];
        foreach (get_declared_classes() as $class) {
            if (!str_starts_with($class, 'AltContext\\Admin\\') || !is_subclass_of($class, AbstractSpaPage::class)) {
                continue;
            }

            $reflection = new ReflectionClass($class);
            if ($reflection->isAbstract()) {
                continue;
            }

            $pages[] = $reflection->newInstance();
        }

        return $pages;
    }

    public function testNoPageLoadingMessageUsesAGlossaryDontSayTerm(): void
    {
        $rows = self::parseGlossaryRows();
        $this->assertNotEmpty($rows, "glossary.md must parse into at least one Say/Don't-say row");

        $pages = self::concreteSpaPages();
        $this->assertNotEmpty($pages, 'at least one concrete AbstractSpaPage subclass must be found');

        foreach ($pages as $page) {
            $method = new ReflectionMethod($page, 'getLoadingMessage');
            $method->setAccessible(true);
            $message = (string) $method->invoke($page);

            foreach ($rows as $row) {
                $hit = self::findDontSayHit($message, $row);
                $this->assertNull(
                    $hit,
                    sprintf(
                        "%s::getLoadingMessage() = %s contains glossary Don't-say term \"%s\" (say \"%s\" instead)",
                        get_class($page),
                        var_export($message, true),
                        (string) $hit,
                        $row['say'],
                    ),
                );
            }
        }
    }
}

<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;
use FilesystemIterator;
use RecursiveCallbackFilterIterator;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use SplFileInfo;

/**
 * R6L-BR-02 / R7: nothing stops the next credentialed egress call site.
 *
 * RecognitionTransport is the only place allowed to open credentialed HTTP to
 * the recognition service (loopback/safe chooser + forced redirection => 0).
 * A brand-new plugin-tree file that calls wp_remote_post with X-API-Key bypasses
 * every require_once / "references RecognitionTransport::" guard. This scan
 * fails on any raw wp_remote_* / wp_safe_remote_* call, string-name reference,
 * or import outside an explicit per-function allowlist — so a sixth call site
 * is a reviewable allowlist line, not a silent green suite.
 *
 * Scope boundary (honest): this guard watches the WordPress `wp_remote_*` /
 * `wp_safe_remote_*` wrapper surface only. Lower-layer HTTP APIs
 * (`WP_Http`, `_wp_http_get_object()`, `curl_exec`, `file_get_contents`,
 * `fsockopen`) bypass it by construction. That is accepted: WP convention and
 * WPCS push developers to the wrappers, and BR-137 is specifically about those
 * wrappers' default redirect-follow walking credentials.
 *
 * Honest limit: the guard cannot distinguish credentialed from uncredentialed
 * call sites without the allowlist. The Vite probe in class-admin.php is
 * uncredentialed; only `wp_remote_head` is permitted there, with the reason
 * in the comment.
 *
 * Forms detected (token scan):
 *   - bare / fully-qualified call: `wp_remote_post(`, `\wp_remote_post(`
 *   - exact string literal equal to a banned name (variable-function /
 *     `call_user_func` family when the full name is a single literal)
 *   - `use function wp_remote_post` imports
 *   - concatenated name construction where a string literal is a proper prefix
 *     of a banned name and the next significant token is `.` (e.g.
 *     `'wp_remote_' . 'post'`), including when that expression is the first
 *     arg of `call_user_func` / `call_user_func_array`
 *
 * Forms NOT detected (accepted boundary — R19-BR-09):
 *   - names assembled without a banned-prefix string fragment in source
 *     (e.g. `chr()` / `sprintf` / fully-variable construction with no
 *     `wp_remote_*` prefix literal)
 *   - indirect callables that never spell a banned name or prefix in a
 *     string or identifier token
 *
 * This guard is defence-in-depth only. The real control for credentialed
 * redirect-walk is RecognitionTransport's `redirection => 0` pin (and the
 * loopback/safe chooser), which is tested separately and thoroughly. No
 * dynamic-construction call site exists in src/ today (independent sweep).
 *
 * @coversNothing
 */
class RecognitionTransportEgressGuardTest extends TestCase
{
    /**
     * Relative paths under the plugin root → banned function names permitted
     * in that file. Adding an entry (or widening a file's set) is a reviewable
     * diff line — the whole point of this guard.
     *
     * @var array<string, list<string>>
     */
    private const ALLOWLIST = [
        // The shared credentialed transport is the only place allowed to choose
        // loopback vs safe remote and force redirection => 0 (BR-137). Full
        // banned set: every wrapper the transport may call or import.
        'src/support/class-recognition-transport.php' => [
            'wp_remote_get',
            'wp_remote_post',
            'wp_remote_request',
            'wp_remote_head',
            'wp_safe_remote_get',
            'wp_safe_remote_post',
            'wp_safe_remote_request',
            'wp_safe_remote_head',
        ],
        // Uncredentialed Vite dev-server reachability probe (wp_remote_head at
        // class-admin.php:223; sends no API key / tenant headers). Only the
        // HEAD helper is permitted — a second credentialed wp_remote_post in
        // this file must remain a reviewable allowlist line.
        'src/admin/class-admin.php' => [
            'wp_remote_head',
        ],
    ];

    /**
     * Functions that open an HTTP egress path via the WP HTTP API wrappers.
     * Enumerated from vendor/php-stubs/wordpress-stubs/wordpress-stubs.php
     * (wp_remote_{request,get,post,head} + wp_safe_remote_{request,get,post,head}).
     * wp_remote_retrieve_* is response inspection only and is intentionally
     * not listed. wp_remote_fopen is a legacy remote-fopen helper, not part of
     * the request-wrapper surface BR-137 gates.
     *
     * @var list<string>
     */
    private const BANNED_FUNCTIONS = [
        'wp_remote_get',
        'wp_remote_post',
        'wp_remote_request',
        'wp_remote_head',
        'wp_safe_remote_get',
        'wp_safe_remote_post',
        'wp_safe_remote_request',
        'wp_safe_remote_head',
    ];

    /**
     * Directory names pruned when walking the plugin root.
     *
     * @var list<string>
     */
    private const PRUNE_DIRS = [
        'vendor',
        'node_modules',
        'tests',
        'dist',
        'build',
        '.git',
        // Gitignored tool caches. PHPStan writes .php cache files that quote the
        // banned names verbatim, so a developer who ran static analysis before
        // the suite got a guard failure that no source change could clear.
        '.phpstan-cache',
        '.phpunit.cache',
    ];

    /**
     * Walks every PHP file under the plugin root (pruning vendor/tests/etc.)
     * and fails on any banned wp_remote_* call, string-name reference, or
     * `use function` import outside the per-function allowlist.
     */
    public function testNoStrayWpRemoteCallsOutsideAllowlist(): void
    {
        $root = realpath(ACX_PLUGIN_DIR);
        $this->assertNotFalse($root, 'plugin root must exist');
        $root = rtrim(str_replace('\\', '/', $root), '/');

        $banned = [];
        foreach (self::BANNED_FUNCTIONS as $fn) {
            $banned[strtolower($fn)] = $fn;
        }

        $violations = [];

        $directory = new RecursiveDirectoryIterator(
            $root,
            FilesystemIterator::SKIP_DOTS
        );
        $filtered = new RecursiveCallbackFilterIterator(
            $directory,
            static function (SplFileInfo $current): bool {
                if ($current->isDir()) {
                    return !in_array($current->getFilename(), self::PRUNE_DIRS, true);
                }

                return $current->isFile() && 'php' === $current->getExtension();
            }
        );

        $iterator = new RecursiveIteratorIterator($filtered);

        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            $path = $file->getPathname();
            $relative = substr(str_replace('\\', '/', $path), strlen($root) + 1);

            $permitted = [];
            if (isset(self::ALLOWLIST[$relative])) {
                foreach (self::ALLOWLIST[$relative] as $fn) {
                    $permitted[strtolower($fn)] = true;
                }
            }

            foreach ($this->findBannedUsages($path, $banned) as $hit) {
                if (isset($permitted[$hit['name']])) {
                    continue;
                }
                $violations[] = sprintf(
                    '%s:%d: %s',
                    $relative,
                    $hit['line'],
                    $hit['name']
                );
            }
        }

        $this->assertSame(
            [],
            $violations,
            "Raw wp_remote_* / wp_safe_remote_* calls must route through "
            . "RecognitionTransport (or be explicitly allowlisted with a reason). "
            . "Offending file(s):\n" . implode("\n", $violations)
        );
    }

    /**
     * Token-based scan: function-call position, exact string names,
     * banned-prefix string concatenation, and `use function` imports.
     * Comments and non-exact string mentions are invisible by construction.
     *
     * @param array<string, string> $banned lowercased name => canonical name
     * @return list<array{name: string, line: int}>
     */
    private function findBannedUsages(string $path, array $banned): array
    {
        $code = file_get_contents($path);
        if (false === $code) {
            return [];
        }

        $tokens = token_get_all($code);
        $hits = [];
        $count = count($tokens);

        for ($i = 0; $i < $count; $i++) {
            $token = $tokens[$i];
            if (!is_array($token)) {
                continue;
            }

            [$id, $text, $line] = $token;

            // Exact string literal equal to a banned name (call_user_func /
            // array_map / variable-function family). Also: a string that is a
            // proper prefix of a banned name followed by `.` (dynamic
            // construction: 'wp_remote_' . 'post').
            if (T_CONSTANT_ENCAPSED_STRING === $id) {
                $value = $this->unquoteString($text);
                $lower = strtolower($value);
                if (isset($banned[$lower])) {
                    $hits[] = ['name' => $banned[$lower], 'line' => $line];
                    continue;
                }

                $concatName = $this->bannedNameForPrefixConcat($lower, $banned, $tokens, $i);
                if (null !== $concatName) {
                    $hits[] = ['name' => $concatName, 'line' => $line];
                }
                continue;
            }

            // use function <banned> ...
            if (T_USE === $id) {
                $fnIdx = $this->nextSignificantIndex($tokens, $i);
                if (null === $fnIdx) {
                    continue;
                }
                $fnTok = $tokens[$fnIdx];
                if (!is_array($fnTok) || T_FUNCTION !== $fnTok[0]) {
                    continue;
                }
                $nameIdx = $this->nextSignificantIndex($tokens, $fnIdx);
                if (null === $nameIdx) {
                    continue;
                }
                $nameTok = $tokens[$nameIdx];
                if (!is_array($nameTok) || T_STRING !== $nameTok[0]) {
                    continue;
                }
                $lower = strtolower($nameTok[1]);
                if (isset($banned[$lower])) {
                    $hits[] = ['name' => $banned[$lower], 'line' => $nameTok[2]];
                }
                continue;
            }

            // PHP 8+ folds \wp_remote_post into a single T_NAME_FULLY_QUALIFIED
            // token (not T_NS_SEPARATOR + T_STRING). Treat both shapes as names.
            $isNameToken = T_STRING === $id
                || (defined('T_NAME_FULLY_QUALIFIED') && T_NAME_FULLY_QUALIFIED === $id)
                || (defined('T_NAME_QUALIFIED') && T_NAME_QUALIFIED === $id)
                || (defined('T_NAME_RELATIVE') && T_NAME_RELATIVE === $id);

            if (!$isNameToken) {
                continue;
            }

            // Strip leading namespace separators / segments to the bare function name.
            $bare = strtolower($text);
            if (str_contains($bare, '\\')) {
                $parts = explode('\\', $bare);
                $bare = (string) end($parts);
            }
            if (!isset($banned[$bare])) {
                continue;
            }

            // Skip method / static property / function-declaration position.
            $prevIdx = $this->prevSignificantIndex($tokens, $i);
            if (null !== $prevIdx) {
                $prev = $tokens[$prevIdx];
                if (is_array($prev)) {
                    $prevId = $prev[0];
                    if (
                        T_OBJECT_OPERATOR === $prevId
                        || T_DOUBLE_COLON === $prevId
                        || T_FUNCTION === $prevId
                        || (defined('T_NULLSAFE_OBJECT_OPERATOR') && T_NULLSAFE_OBJECT_OPERATOR === $prevId)
                    ) {
                        continue;
                    }
                }
            }

            // Function-call position: next significant token is '('.
            // Covers bare wp_remote_post( and \wp_remote_post( (fully-qualified).
            $nextIdx = $this->nextSignificantIndex($tokens, $i);
            if (null === $nextIdx) {
                continue;
            }
            $next = $tokens[$nextIdx];
            if ('(' === $next) {
                $hits[] = ['name' => $banned[$bare], 'line' => $line];
            }
        }

        return $hits;
    }

    /**
     * If the token at $stringIndex starts a pure string-literal concatenation
     * that reconstructs a banned name (e.g. `'wp_remote_' . 'post'`), return
     * that name. Requires the left-most fragment to be a `wp_remote_` /
     * `wp_safe_remote_` stem so short fragments do not false-positive.
     *
     * Only walks when this string is the left-most fragment of the concat
     * chain (previous significant token is not `.`) so each expression yields
     * one hit rather than one per fragment.
     *
     * @param array<string, string> $banned
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function bannedNameForPrefixConcat(
        string $prefix,
        array $banned,
        array $tokens,
        int $stringIndex
    ): ?string {
        if ('' === $prefix) {
            return null;
        }

        // Only flag stems that already identify the WP HTTP wrapper family.
        $isWrapperStem = str_starts_with($prefix, 'wp_remote_')
            || str_starts_with($prefix, 'wp_safe_remote_');
        if (!$isWrapperStem) {
            return null;
        }

        // Skip mid-chain fragments ('post' in 'wp_remote_' . 'post').
        $prevIdx = $this->prevSignificantIndex($tokens, $stringIndex);
        if (null !== $prevIdx && '.' === $tokens[$prevIdx]) {
            return null;
        }

        $nextIdx = $this->nextSignificantIndex($tokens, $stringIndex);
        if (null === $nextIdx || '.' !== $tokens[$nextIdx]) {
            return null;
        }

        // Reconstruct pure string-literal concatenation: 'a' . 'b' . 'c'
        $assembled = $prefix;
        $cursor = $stringIndex;
        while (true) {
            $dotIdx = $this->nextSignificantIndex($tokens, $cursor);
            if (null === $dotIdx || '.' !== $tokens[$dotIdx]) {
                break;
            }
            $rhsIdx = $this->nextSignificantIndex($tokens, $dotIdx);
            if (null === $rhsIdx) {
                break;
            }
            $rhs = $tokens[$rhsIdx];
            if (!is_array($rhs) || T_CONSTANT_ENCAPSED_STRING !== $rhs[0]) {
                // Non-literal RHS (variable / call) — still flag if the stem
                // alone is a proper prefix of a banned name.
                foreach ($banned as $lower => $canonical) {
                    if ($lower !== $assembled && str_starts_with($lower, $assembled)) {
                        return $canonical;
                    }
                }

                return null;
            }
            $assembled .= strtolower($this->unquoteString($rhs[1]));
            $cursor = $rhsIdx;
        }

        if (isset($banned[$assembled])) {
            return $banned[$assembled];
        }

        // Incomplete but clearly aiming at a banned wrapper (e.g. 'wp_remote_'
        // . $method). Flag the first matching banned name for the message.
        foreach ($banned as $lower => $canonical) {
            if ($lower !== $assembled && str_starts_with($lower, $assembled)) {
                return $canonical;
            }
        }

        return null;
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function nextSignificantIndex(array $tokens, int $from): ?int
    {
        $count = count($tokens);
        for ($i = $from + 1; $i < $count; $i++) {
            $token = $tokens[$i];
            if ($this->isInsignificant($token)) {
                continue;
            }
            return $i;
        }

        return null;
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function prevSignificantIndex(array $tokens, int $from): ?int
    {
        for ($i = $from - 1; $i >= 0; $i--) {
            $token = $tokens[$i];
            if ($this->isInsignificant($token)) {
                continue;
            }
            return $i;
        }

        return null;
    }

    /**
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function isInsignificant($token): bool
    {
        if (!is_array($token)) {
            return false;
        }

        return in_array($token[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true);
    }

    private function unquoteString(string $text): string
    {
        if (strlen($text) < 2) {
            return $text;
        }

        $quote = $text[0];
        if (("'" === $quote || '"' === $quote) && $text[strlen($text) - 1] === $quote) {
            return substr($text, 1, -1);
        }

        return $text;
    }
}

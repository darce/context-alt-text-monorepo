import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '..', '..', '..', '..');
const scriptPath = path.join(repoRoot, 'scripts', 'local-wp-cli.sh');

describe('local-wp-cli.sh', () => {
  it('fails when socket metadata is missing', () => {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      LOCALWP_SITE_PATH: '/tmp/site',
      ALT_CONTEXT_WP_CLI_DRY_RUN: '1',
    };
    delete env.LOCALWP_MYSQL_SOCKET;

    const result = spawnSync('bash', [scriptPath, 'core', 'version'], { env, encoding: 'utf8' });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain('LOCALWP_MYSQL_SOCKET');
  });

  it('outputs the computed WP-CLI command when dry-run is enabled', () => {
    const env = {
      ...process.env,
      LOCALWP_MYSQL_SOCKET: '/tmp/mysql.sock',
      LOCALWP_SITE_PATH: '/Users/example/Local Sites/alt-context/app/public',
      LOCALWP_SITE_URL: 'http://example.test',
      ALT_CONTEXT_WP_CLI_DRY_RUN: '1',
    };

    const result = spawnSync('bash', [scriptPath, 'core', 'version'], { env, encoding: 'utf8' });
    expect(result.status).toBe(0);
    expect(result.stdout).toContain('mysqli.default_socket=/tmp/mysql.sock');
    expect(result.stdout).toContain('--path=/Users/example/Local Sites/alt-context/app/public');
    expect(result.stdout).toContain('--url=http://example.test');
    expect(result.stdout).toContain('core version');
  });
});

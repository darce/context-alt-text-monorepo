<?php

declare(strict_types=1);

namespace AltContext\Api;

use function rawurlencode;
use function str_replace;

/**
 * Canonical upstream paths used by the retention proxy callers.
 */
final class ProxyRoutes
{
    public const ROUTE_KIND_STATIC = 'static';
    public const ROUTE_KIND_PARAMETERIZED = 'parameterized';

    public const GET_RETENTION_POLICY_PATH = '/recognition/retention/policy';
    public const GET_RETENTION_AUDIT_PATH = '/recognition/retention/audit';
    public const PATCH_RETENTION_POLICY_PATH = '/recognition/retention/policy';
    public const POST_RETENTION_POLICY_PRESET_PATH = '/recognition/retention/policy/preset';
    public const POST_RETENTION_EXPORT_PATH = '/recognition/retention/export';
    public const GET_RETENTION_EXPORT_STATUS_PATH = '/recognition/retention/export/{param_0}/status';
    public const GET_RETENTION_EXPORT_DATA_PATH = '/recognition/retention/export/{param_0}/data';
    public const POST_RETENTION_PURGE_PATH = '/recognition/retention/purge';
    public const POST_RETENTION_IMPORT_PATH = '/recognition/retention/import';

    /**
     * @var list<array{method: string, path: string, kind: string, route_level_not_found: bool}>
     */
    private const ROUTES = array(
        array(
            'method' => 'GET',
            'path' => self::GET_RETENTION_POLICY_PATH,
            'kind' => self::ROUTE_KIND_STATIC,
            'route_level_not_found' => false,
        ),
        array(
            'method' => 'GET',
            'path' => self::GET_RETENTION_AUDIT_PATH,
            'kind' => self::ROUTE_KIND_STATIC,
            'route_level_not_found' => false,
        ),
        array(
            'method' => 'PATCH',
            'path' => self::PATCH_RETENTION_POLICY_PATH,
            'kind' => self::ROUTE_KIND_STATIC,
            'route_level_not_found' => false,
        ),
        array(
            'method' => 'POST',
            'path' => self::POST_RETENTION_POLICY_PRESET_PATH,
            'kind' => self::ROUTE_KIND_STATIC,
            'route_level_not_found' => false,
        ),
        array(
            'method' => 'POST',
            'path' => self::POST_RETENTION_EXPORT_PATH,
            'kind' => self::ROUTE_KIND_STATIC,
            'route_level_not_found' => false,
        ),
        array(
            'method' => 'GET',
            'path' => self::GET_RETENTION_EXPORT_STATUS_PATH,
            'kind' => self::ROUTE_KIND_PARAMETERIZED,
            'route_level_not_found' => true,
        ),
        array(
            'method' => 'GET',
            'path' => self::GET_RETENTION_EXPORT_DATA_PATH,
            'kind' => self::ROUTE_KIND_PARAMETERIZED,
            'route_level_not_found' => true,
        ),
        array(
            'method' => 'POST',
            'path' => self::POST_RETENTION_PURGE_PATH,
            'kind' => self::ROUTE_KIND_STATIC,
            'route_level_not_found' => false,
        ),
        array(
            'method' => 'POST',
            'path' => self::POST_RETENTION_IMPORT_PATH,
            'kind' => self::ROUTE_KIND_STATIC,
            'route_level_not_found' => false,
        ),
    );

    /**
     * @return list<array{method: string, path: string, kind: string, route_level_not_found: bool}>
     */
    public static function all(): array
    {
        return self::ROUTES;
    }

    /**
     * @return list<array{method: string, path: string, kind: string, route_level_not_found: bool}>
     */
    public static function routes(): array
    {
        return self::all();
    }

    public static function export_job_status_path(string $job_id): string
    {
        return self::build_parameterized_path(self::GET_RETENTION_EXPORT_STATUS_PATH, $job_id);
    }

    public static function export_job_data_path(string $job_id): string
    {
        return self::build_parameterized_path(self::GET_RETENTION_EXPORT_DATA_PATH, $job_id);
    }

    private static function build_parameterized_path(string $template, string $job_id): string
    {
        return str_replace('{param_0}', rawurlencode($job_id), $template);
    }
}

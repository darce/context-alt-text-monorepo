# API Contracts

Human-readable documentation of the live integration between WordPress plugin and Recognition Service.

## Contents

### WordPress REST API (WP → FastAPI Proxy)

| File                                   | Description                                                                 |
| -------------------------------------- | --------------------------------------------------------------------------- |
| [clustering-api.md](clustering-api.md) | Recognition endpoints (`/wp-json/acx/v1/recognition/*`) |

### Recognition Service (FastAPI)

| File                                                   | Description                             |
| ------------------------------------------------------ | --------------------------------------- |
| [recognition-clustering.md](recognition-clustering.md) | Recognition HTTP API (`/recognition/*`) |

### Security & Integration

| File                                                           | Description                                  |
| -------------------------------------------------------------- | -------------------------------------------- |
| [security.md](security.md)                                     | API key auth, tenant isolation, RLS policies |
| [wordpress-backend-contract.md](wordpress-backend-contract.md) | Progressive learning workflow (reference)    |

## Machine-Readable Schemas

For code generation (TypeScript, PHP DTOs, Python Pydantic), see:

```
packages/shared-contracts/
├── schemas/
│   ├── coverage-stats.schema.json
│   ├── recognition-job.schema.json
│   ├── recognition-observation.schema.json
│   ├── roster-entry.schema.json
│   └── workbench-media-item.schema.json
└── recognition/
    └── roster-roundtrip.sample.json
```

## Key Integration Points

### Tenant ID

WordPress generates tenant ID from site URL:

```php
$tenant_id = md5(get_site_url());  // 32-char hex string
```

### Authentication

- Header: `Authorization: Bearer <api_key>` or `X-Api-Key: <api_key>`
- Development: Use `DEV_API_KEYS` environment variable
- WordPress: Stored in `context_alt_text_recognition_api_key` option

### Request Flow

```
React UI → WP REST API → RecognitionController → FastAPI → PostgreSQL
```

The WordPress plugin injects `tenant_id` and forwards requests to the recognition service.

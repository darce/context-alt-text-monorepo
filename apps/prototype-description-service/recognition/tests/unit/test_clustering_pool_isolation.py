"""E15-3a-BR-21 Slice 4: clustering pool isolation.

The clustering-jobs write path runs on a dedicated engine + session factory so
that a saturated clustering pool (e.g. many tenants hitting the ``SELECT ... FOR
UPDATE`` path under contention) cannot block unrelated read traffic on the
business pool or the operator ``/health/detailed`` surface on the observability
pool.

Proof obligations (task plan):

* ``engine is not clustering_engine`` -- distinct ``AsyncEngine`` instances.
* Clustering pool is narrower than the business pool so business traffic keeps
  capacity while clustering is under contention.
* Settings expose ``clustering_pool_size`` / ``clustering_max_overflow`` /
  ``clustering_pool_timeout`` as first-class env-driven overrides so operators
  can tune per-deploy without code changes.
"""

from __future__ import annotations

from db.settings import get_database_settings


def test_clustering_pool_settings_defaults(monkeypatch) -> None:
    """Defaults: pool_size=2, max_overflow=1, pool_timeout=5 (per task plan line 223)."""
    for key in (
        "DB_CLUSTERING_POOL_SIZE",
        "DB_CLUSTERING_MAX_OVERFLOW",
        "DB_CLUSTERING_POOL_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)

    get_database_settings.cache_clear()
    try:
        settings = get_database_settings()
    finally:
        get_database_settings.cache_clear()

    assert settings.clustering_pool_size == 2, "default clustering pool_size must be 2 per task plan S4 spec"
    assert settings.clustering_max_overflow == 1, "default clustering max_overflow must be 1 per task plan S4 spec"
    assert settings.clustering_pool_timeout == 5


def test_clustering_pool_settings_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DB_CLUSTERING_POOL_SIZE", "4")
    monkeypatch.setenv("DB_CLUSTERING_MAX_OVERFLOW", "2")
    monkeypatch.setenv("DB_CLUSTERING_POOL_TIMEOUT", "7")

    get_database_settings.cache_clear()
    try:
        settings = get_database_settings()
    finally:
        get_database_settings.cache_clear()

    assert settings.clustering_pool_size == 4
    assert settings.clustering_max_overflow == 2
    assert settings.clustering_pool_timeout == 7


def test_clustering_engine_is_separate_from_business_engine() -> None:
    """``engine is not clustering_engine`` is the core bulkhead invariant."""
    from db.session import clustering_engine, engine

    assert engine is not clustering_engine
    # Session factories must be distinct too, else a handler grabbing
    # clustering_async_session_factory() would still land on the business pool.
    from db.session import async_session_factory, clustering_async_session_factory

    assert async_session_factory is not clustering_async_session_factory


def test_clustering_pool_is_narrower_than_business_pool() -> None:
    """Bulkhead invariant: clustering pool sizing must be strictly smaller.

    Saturation of the clustering write path must not consume business-pool
    capacity. We assert the relationship via the settings surface so this
    stays robust against SQLAlchemy pool-class changes (QueuePool, NullPool
    in tests, etc.).
    """
    settings = get_database_settings()
    assert settings.clustering_pool_size < settings.pool_size, (
        f"clustering pool_size={settings.clustering_pool_size} must be < business pool_size={settings.pool_size}"
    )
    assert settings.clustering_max_overflow < settings.max_overflow, (
        f"clustering max_overflow={settings.clustering_max_overflow} must be < business max_overflow={settings.max_overflow}"
    )
    assert settings.clustering_pool_size >= 1

"""FastAPI dependency providers for the multipart upload ObjectStore (E15-11).

The multipart variant of /recognition/analyze depends on a request-scoped
ObjectStore bound to ``auth.tenant_claim`` so per-blob tenant binding is
enforced at the storage layer (every put/open is scoped to the
authenticated tenant's prefix).

Kept in its own module so the provider can be unit-tested without
spinning up the full FastAPI app.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from recognition.application.storage import FilesystemObjectStore, ObjectStore
from recognition.config import get_settings as _get_recognition_settings
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http.dependencies import require_write_access
from recognition.interface_adapters.http.deps.auth import AuthContext


def _settings_default() -> RecognitionSettings:
    return _get_recognition_settings()


def get_object_store(
    *,
    auth: AuthContext,
    settings: RecognitionSettings | None = None,
) -> ObjectStore:
    """Return a request-scoped ObjectStore bound to ``auth.tenant_claim``.

    Designed to be used as a FastAPI dependency on the multipart route::

        store = Depends(get_object_store_for_request)

    The wrapper ``get_object_store_for_request`` (defined below) threads
    ``auth`` and ``settings`` through ``Depends`` so handlers can call
    ``store: ObjectStore = Depends(get_object_store_for_request)``.

    Defense-in-depth: refuses an empty tenant_claim so a route that forgets
    to gate ``require_auth`` cannot mint a cross-tenant store.
    """
    if settings is None:
        settings = _settings_default()

    tenant_claim = (auth.tenant_claim or "").strip()
    if not tenant_claim:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing tenant claim; cannot construct ObjectStore",
        )

    blob_root = settings.blob_root
    blob_root.mkdir(parents=True, exist_ok=True)

    return FilesystemObjectStore(root=blob_root, tenant_id=tenant_claim)


def get_object_store_for_request(
    auth: AuthContext = Depends(require_write_access),  # noqa: B008 - FastAPI DI pattern
    settings: RecognitionSettings = Depends(_settings_default),  # noqa: B008
) -> ObjectStore:
    """FastAPI dependency that returns a tenant-bound ObjectStore.

    Bound to ``require_write_access`` because the multipart upload path is
    a write operation; the route still keeps ``Depends(require_write_access)``
    in its own signature so the auth gate runs even if a future refactor
    drops this dependency. Settings comes from ``_settings_default`` (the
    process-global RecognitionSettings) and is overridable in tests via
    ``app.dependency_overrides[_settings_default]``.
    """
    return get_object_store(auth=auth, settings=settings)

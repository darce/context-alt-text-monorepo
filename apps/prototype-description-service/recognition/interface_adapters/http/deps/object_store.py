"""FastAPI dependency providers for the multipart upload ObjectStore (E15-11).

The multipart variant of /recognition/analyze depends on a Callable that,
given a tenant_id, returns an ``ObjectStore`` bound to that tenant's
storage prefix. The route resolves the tenant_id from the validated
request envelope (after the auth/envelope mismatch check), so admin keys
with no ``auth.tenant_claim`` can target any tenant while tenant-scoped
keys are still pinned by the route's mismatch guard.

The factory is the only DI surface this module exports; an earlier
``get_object_store_for_request`` wrapper bound the store directly to
``auth.tenant_claim`` and rejected admin keys before the route could
apply its envelope-based tenant resolution. That wrapper has been removed
to align the DI with the route's documented contract.

Kept in its own module so the factory can be unit-tested without
spinning up the full FastAPI app.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from recognition.application.storage import FilesystemObjectStore, ObjectStore
from recognition.config import get_settings as _get_recognition_settings
from recognition.config.settings import RecognitionSettings

ObjectStoreFactory = Callable[[str], ObjectStore]


def _settings_default() -> RecognitionSettings:
    return _get_recognition_settings()


def get_object_store_factory_for_request(
    settings: RecognitionSettings = Depends(_settings_default),  # noqa: B008
) -> ObjectStoreFactory:
    """Return a Callable[[tenant_id], ObjectStore] bound to the configured
    backend (E15-11 BR-14).

    The multipart route's BackgroundTask runs after the request has
    returned, so a request-scoped ``object_store`` is no longer safe to
    capture. The route used to read ``object_store.root`` and rebuild a
    ``FilesystemObjectStore`` directly, which leaked the filesystem
    implementation through the ``ObjectStore`` protocol and blocked
    Slice B's OCI swap. This factory keeps the protocol clean: the
    backend selection lives here (filesystem in Slice A, OCI in Slice B
    by override), and the route just calls ``factory(tenant_id)`` without
    poking at impl-private attributes.

    The factory rejects an empty tenant_id with 401 as defense in depth,
    even though the route validates the envelope tenant_id before
    invoking the factory.

    Tests override via ``app.dependency_overrides[get_object_store_factory_for_request]``.
    """
    blob_root = settings.blob_root
    blob_root.mkdir(parents=True, exist_ok=True)

    def _factory(tenant_id: str) -> ObjectStore:
        tenant_id = (tenant_id or "").strip()
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing tenant claim; cannot construct ObjectStore",
            )
        return FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)

    return _factory

"""Build-bound source identity. No runtime source discovery or providers."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat


@dataclass(frozen=True, kw_only=True)
class SourceIdentityV1:
    source_identity_version: int
    source_git_sha: str
    source_tree: str
    build_context_manifest_sha256: str
    service_lock_sha256: str
    image_variant: str
    build_time: str
    identity_document_sha256: str

    def __post_init__(self):
        if type(self.source_identity_version) is not int or self.source_identity_version != 1:
            raise ValueError("incompatible_version")
        for name, width in (("source_git_sha", 40), ("source_tree", 40),
                            ("build_context_manifest_sha256", 64), ("service_lock_sha256", 64),
                            ("identity_document_sha256", 64)):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{%d}" % width, value) is None:
                raise ValueError("invalid_build_binding")
        if self.image_variant not in {"recognition", "vlm"}:
            raise ValueError("invalid_image_variant")
        from datetime import datetime
        if not isinstance(self.build_time, str):
            raise ValueError("invalid_build_time")
        try:
            parsed = datetime.fromisoformat(self.build_time.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("invalid_build_time") from None
        if parsed.tzinfo is None:
            raise ValueError("invalid_build_time")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(document):
    # The digest covers the canonical document excluding its own digest field.
    return hashlib.sha256(_canonical({k: v for k, v in document.items()
                                     if k != "identity_document_sha256"})).hexdigest()


def load_baked_source_identity(path: Path = Path("/app/.source-identity.json"), *,
                               max_record_bytes: int = 16384) -> SourceIdentityV1:
    if type(max_record_bytes) is not int or not 0 < max_record_bytes <= 1048576:
        raise ValueError("invalid_size_cap")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_record_bytes:
            raise ValueError("invalid_identity_file")
        raw = stream.read(max_record_bytes + 1)
    if len(raw) > max_record_bytes:
        raise ValueError("identity_oversized")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_identity_field")
            result[key] = value
        return result
    document = json.loads(raw, object_pairs_hook=unique)
    identity = SourceIdentityV1(**document)
    if identity.identity_document_sha256 != _digest(document):
        raise ValueError("identity_digest_mismatch")
    for name in ("GIT_COMMIT_SHA", "APP_GIT_COMMIT_SHA"):
        override = os.environ.get(name)
        if override is not None and override != identity.source_git_sha:
            raise ValueError("source_environment_conflict")
    return identity


def write_build_source_identity(*, output: Path, source_git_sha: str, source_tree: str,
                                build_context_manifest_sha256: str, service_lock_sha256: str,
                                image_variant: str, build_time: str) -> SourceIdentityV1:
    """All facts are explicit build arguments; never infer them from ENV or disk."""
    document = dict(source_identity_version=1, source_git_sha=source_git_sha,
                    source_tree=source_tree, build_context_manifest_sha256=build_context_manifest_sha256,
                    service_lock_sha256=service_lock_sha256, image_variant=image_variant, build_time=build_time)
    document["identity_document_sha256"] = _digest(document)
    identity = SourceIdentityV1(**document)
    with open(output, "xb") as stream:
        stream.write(_canonical(asdict(identity)))
    os.chmod(output, 0o444)
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    for field in ("source_git_sha", "source_tree", "build_context_manifest_sha256",
                  "service_lock_sha256", "image_variant", "build_time"):
        parser.add_argument("--" + field.replace("_", "-"), required=True)
    write_build_source_identity(**vars(parser.parse_args()))

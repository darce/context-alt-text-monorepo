"""Scanning subdomain.

Provides identity scanning functionality:
- IdentityScanService: Scans media for faces and persists identities
"""

from recognition.application.scanning.identity_scan_service import IdentityScanService

__all__ = ["IdentityScanService"]

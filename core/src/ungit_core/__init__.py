"""Pure Ungit core domain API."""

from .api import (
    add_files,
    build_delivery_manifest,
    build_tree,
    create_commit,
    diff_trees,
    init_repository,
    read_commit,
    read_tree,
    resolve_ref,
    scan_files,
)
from .hashing import canonical_json, content_hash, object_id
from .client import CoreClient, CoreClientError, DEFAULT_CORE_URL
from .croc import CrocError, CrocLayer
from .models import (
    Commit,
    DeliveryManifest,
    DiffEntry,
    Index,
    IndexEntry,
    Tree,
    TreeEntry,
)
from .payload import (
    PAYLOAD_NAME,
    PayloadError,
    build_delivery_payload,
    compute_payload_hash,
    extract_delivery_payload,
    read_manifest,
    verify_payload,
)
from .service import serve_core
from .service_store import (
    CoreForbidden,
    CoreNotFound,
    CoreServiceStore,
    CoreStoreError,
    CoreUnauthorized,
    DEFAULT_CORE_ROOT,
)
from .store import RepositoryStore

__all__ = [
    "Commit",
    "CoreClient",
    "CoreClientError",
    "CoreForbidden",
    "CoreNotFound",
    "CoreServiceStore",
    "CoreStoreError",
    "CoreUnauthorized",
    "CrocError",
    "CrocLayer",
    "DEFAULT_CORE_ROOT",
    "DEFAULT_CORE_URL",
    "DeliveryManifest",
    "DiffEntry",
    "Index",
    "IndexEntry",
    "PAYLOAD_NAME",
    "PayloadError",
    "RepositoryStore",
    "Tree",
    "TreeEntry",
    "add_files",
    "build_delivery_manifest",
    "build_tree",
    "canonical_json",
    "build_delivery_payload",
    "content_hash",
    "compute_payload_hash",
    "create_commit",
    "diff_trees",
    "extract_delivery_payload",
    "init_repository",
    "object_id",
    "read_manifest",
    "read_commit",
    "read_tree",
    "resolve_ref",
    "scan_files",
    "serve_core",
    "verify_payload",
]

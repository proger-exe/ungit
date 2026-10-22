"""Storage exception types."""


class StorageError(Exception):
    """Base class for storage errors."""


class RepositoryNotFound(StorageError):
    """Repository metadata is missing."""


class ObjectNotFound(StorageError):
    """Requested object does not exist."""


class InvalidStoragePath(StorageError):
    """Unsafe path segment or storage identifier."""

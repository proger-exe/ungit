"""Core exception types."""


class UngitCoreError(Exception):
    """Base class for core errors."""


class InvalidPathError(UngitCoreError):
    """Path is absolute, outside root, or otherwise unsafe."""


class InvalidObjectError(UngitCoreError):
    """Object data does not match the core contract."""


class RepositoryError(UngitCoreError):
    """Repository state is missing or invalid."""

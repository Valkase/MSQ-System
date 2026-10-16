"""Errors raised by the backup and restore tools."""


class BackupError(Exception):
    """A backup or restore step failed. The message is safe to show or log."""
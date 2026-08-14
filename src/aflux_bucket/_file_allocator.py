import shutil
import tempfile
import weakref
from pathlib import Path
from types import TracebackType
from typing import Self

import uuid_utils.compat


class FileAllocator:
    """Allocate unique local paths beneath a directory.

    Files created at allocated paths belong to the caller.
    The caller deletes them after use.

    When `path` is omitted, the allocator creates a temporary directory.
    That directory has best-effort cleanup when the allocator is reclaimed.
    Callers must not rely on that cleanup.

    When `path` is supplied, its creator owns the directory and its cleanup.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            self._path = Path(tempfile.mkdtemp()).resolve()
            self._path_finalizer = weakref.finalize(self, shutil.rmtree, self._path, ignore_errors=True)
        else:
            self._path = Path(path).resolve()
            self._path.mkdir(parents=True, exist_ok=True)
            self._path_finalizer = None

        if any(self._path.iterdir()):
            msg = "FileAllocator base path should be empty."
            raise ValueError(msg)

        self._closed = False

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_open(self) -> None:
        if not self._closed:
            return
        msg = "FileAllocator is closed."
        raise RuntimeError(msg)

    def allocate(self, suffix_like: str | Path = "") -> Path:
        """Return a unique local path without creating a file.

        The caller owns a file created at the returned path.
        """
        self._ensure_open()
        suffix = "".join(Path(suffix_like).suffixes)
        name = f"{uuid_utils.compat.uuid7().hex}{suffix}"
        return (self._path / name).resolve()

    def make_child(self) -> "FileAllocator":
        """Create an independent allocator beneath this allocator's directory.

        The parent allocator must remain alive while the child is used.
        """
        self._ensure_open()
        return FileAllocator(tempfile.mkdtemp(dir=self._path))

    def clear(self) -> None:
        """Clear contents while keeping the base path reusable."""
        self._ensure_open()
        if not self._path.exists():
            return
        for item in self._path.iterdir():
            if item.is_file():
                item.unlink()
                continue
            shutil.rmtree(item, ignore_errors=True)

    def close(self) -> None:
        """Clear contents and remove the base path."""
        if self._closed:
            return

        self.clear()
        self._path.rmdir()

        if self._path_finalizer is not None:
            self._path_finalizer.detach()
            self._path_finalizer = None

        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

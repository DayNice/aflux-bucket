import shutil
import tempfile
import weakref
from pathlib import Path
from types import TracebackType
from typing import Self

import uuid_utils.compat


class FileAllocator:
    """Allocate temporary file paths.

    The caller owns the paths returned by `allocate` and must delete them after use.

    The base path must be empty when the allocator is created.
    If omitted, a temporary path is created with best-effort finalizer cleanup.
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
        """Return a unique file path without creating the file."""
        self._ensure_open()
        suffix = "".join(Path(suffix_like).suffixes)
        name = f"{uuid_utils.compat.uuid7().hex}{suffix}"
        return (self._path / name).resolve()

    def make_child(self) -> "FileAllocator":
        """Create a child allocator under the base path."""
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

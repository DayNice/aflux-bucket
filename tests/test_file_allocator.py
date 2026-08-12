from pathlib import Path

import pytest

from aflux_bucket import FileAllocator


class TestFileAllocator:
    def test_nonempty_explicit_path_is_rejected_and_preserved(self, tmp_path: Path) -> None:
        allocator_path = tmp_path / "allocator"
        allocator_path.mkdir()
        existing_file = allocator_path / "existing.txt"
        existing_file.write_bytes(b"data")

        with pytest.raises(ValueError, match="should be empty"):
            FileAllocator(allocator_path)

        assert existing_file.read_bytes() == b"data"

    def test_allocate_unique_paths(self, tmp_path: Path) -> None:
        allocator = FileAllocator(tmp_path)
        path1 = allocator.allocate("file.txt")
        path2 = allocator.allocate("file.txt")
        assert path1 != path2

    def test_allocate_preserves_suffix(self, tmp_path: Path) -> None:
        allocator = FileAllocator(tmp_path)
        path = allocator.allocate("archive.tar.gz")
        assert "".join(path.suffixes) == ".tar.gz"

    def test_allocate_no_suffix(self, tmp_path: Path) -> None:
        allocator = FileAllocator(tmp_path)
        path = allocator.allocate()
        assert path.suffix == ""

    def test_allocate_within_path(self, tmp_path: Path) -> None:
        allocator = FileAllocator(tmp_path)
        path = allocator.allocate("file.txt")
        assert path.is_relative_to(tmp_path)

    def test_clear_removes_files(self, tmp_path: Path) -> None:
        allocator = FileAllocator(tmp_path)
        path = allocator.allocate("file.txt")
        path.write_bytes(b"data")
        allocator.clear()
        assert not path.exists()
        assert tmp_path.exists()

    def test_clear_removes_subdirs(self, tmp_path: Path) -> None:
        allocator = FileAllocator(tmp_path)
        child = allocator.make_child()
        child_path = child.path
        allocator.clear()
        assert not child_path.exists()
        assert tmp_path.exists()

    def test_make_child_path_inside_parent(self, tmp_path: Path) -> None:
        allocator = FileAllocator(tmp_path)
        child = allocator.make_child()
        assert child.path.is_relative_to(allocator.path)

    def test_context_manager_clears(self, tmp_path: Path) -> None:
        with FileAllocator(tmp_path) as allocator:
            path = allocator.allocate("file.txt")
            path.write_bytes(b"data")
            assert path.exists()
        assert not path.exists()
        assert tmp_path.exists()

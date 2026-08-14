from pathlib import Path

import pytest

from aflux_bucket import DirBucket, FileAllocator


class TestDirBucket:
    def test_path_traversal_prevention(self, tmp_path: Path) -> None:
        bucket = DirBucket(tmp_path)
        with pytest.raises(ValueError, match="escapes"):
            bucket.get_file("../outside.txt")
        with pytest.raises(ValueError, match="escapes"):
            bucket.put_bytes(b"data", "../outside.txt")
        with pytest.raises(ValueError, match="escapes"):
            bucket.with_prefix("../outside")
        with pytest.raises(ValueError, match="escapes"):
            bucket.with_prefix(str(tmp_path.parent / "outside"))

    def test_put_and_get(self, tmp_path: Path) -> None:
        bucket = DirBucket(tmp_path)
        remote_path = "a/b/c/file.txt"
        data = b"hello world"

        bucket.put_bytes(data, remote_path)
        assert bucket.check_file_exists(remote_path)
        assert bucket.get_bytes(remote_path) == data

        local_file = bucket.get_file(remote_path)
        assert local_file.read_bytes() == data

    def test_local_file_is_temporary(self, tmp_path: Path) -> None:
        remote_file = tmp_path / "file.txt"
        remote_file.write_text("hello")

        bucket = DirBucket(tmp_path)
        local_file = bucket.get_file("file.txt")
        assert local_file != remote_file

        local_file.unlink()
        assert remote_file.exists()

    def test_delete_and_cleanup(self, tmp_path: Path) -> None:
        bucket = DirBucket(tmp_path)
        path1 = "nested/dir/file1.txt"
        path2 = "nested/file2.txt"

        bucket.put_bytes(b"data", path1)
        bucket.put_bytes(b"data", path2)

        bucket.delete_file(path1)

        assert not bucket.check_file_exists(path1)
        assert not (tmp_path / "nested" / "dir").exists()
        assert (tmp_path / "nested").exists()
        assert bucket.check_file_exists(path2)

    def test_external_file_allocator_is_not_closed(self, tmp_path: Path) -> None:
        root_dir = tmp_path / "root"
        allocator = FileAllocator(tmp_path / "temp")
        bucket = DirBucket(root_dir, file_allocator=allocator)

        bucket.put_bytes(b"data", "file.txt")
        local_file = bucket.get_file("file.txt")
        assert local_file.exists()
        assert allocator.path.exists()

        allocator.close()

        assert not allocator.path.exists()

    def test_with_prefix(self, tmp_path: Path) -> None:
        bucket = DirBucket(tmp_path)
        child = bucket.with_prefix("sub")
        child.put_bytes(b"data", "file.txt")
        assert child.check_file_exists("file.txt")
        assert bucket.check_file_exists("sub/file.txt")

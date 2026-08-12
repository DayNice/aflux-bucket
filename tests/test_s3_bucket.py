import concurrent.futures
import threading
import time
from pathlib import Path
from typing import cast

import boto3
import pytest
from moto import mock_aws
from pytest_mock import MockerFixture

from aflux_bucket import S3Bucket


@pytest.fixture
def s3_client():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client


class TestS3Bucket:
    def test_put_and_get(self, s3_client) -> None:
        bucket = S3Bucket("test-bucket", s3_client=s3_client)
        remote_path = "a/b/c/file.txt"
        data = b"hello s3"

        bucket.put_bytes(data, remote_path)
        assert bucket.check_file_exists(remote_path)
        assert bucket.get_bytes(remote_path) == data

    def test_missing_file_exists(self, s3_client) -> None:
        bucket = S3Bucket("test-bucket", s3_client=s3_client)
        assert not bucket.check_file_exists("missing.txt")

    def test_get_bytes_returns_current_content(self, s3_client) -> None:
        bucket = S3Bucket("test-bucket", s3_client=s3_client)
        remote_path = "data.txt"

        bucket.put_bytes(b"v1", remote_path)
        assert bucket.get_bytes(remote_path) == b"v1"

        s3_client.put_object(Bucket="test-bucket", Key="data.txt", Body=b"v2")
        assert bucket.get_bytes(remote_path) == b"v2"

    def test_context_manager_cleanup(self, s3_client, tmp_path: Path) -> None:
        with S3Bucket("test-bucket", temp_dir=tmp_path, s3_client=s3_client) as bucket:
            remote_path = "temp.txt"
            bucket.put_bytes(b"data", remote_path)
            local_file = bucket.get_file(remote_path)
            assert local_file.exists()

        assert not tmp_path.exists()

    def test_close_removes_temp_dir_and_rejects_use(self, s3_client, tmp_path: Path) -> None:
        temp_dir = tmp_path / "temp"
        bucket = S3Bucket("test-bucket", temp_dir=temp_dir, s3_client=s3_client)
        bucket.put_bytes(b"data", "file.txt")

        bucket.close()

        assert not temp_dir.exists()
        with pytest.raises(RuntimeError, match="closed"):
            bucket.check_file_exists("file.txt")
        bucket.close()

    def test_close_waits_for_active_download(self, s3_client, tmp_path: Path, mocker: MockerFixture) -> None:
        download_started = threading.Event()
        allow_download = threading.Event()
        old_download_file = s3_client.download_file

        def mock_download_file(*args, **kwargs):
            download_started.set()
            allow_download.wait()
            return old_download_file(*args, **kwargs)

        mocker.patch.object(s3_client, "download_file", side_effect=mock_download_file)

        temp_dir = tmp_path / "temp"
        bucket = S3Bucket("test-bucket", temp_dir=temp_dir, s3_client=s3_client)
        bucket.put_bytes(b"data", "file.txt")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            download_future = executor.submit(bucket.get_file, "file.txt")
            assert download_started.wait(timeout=5)

            close_future = executor.submit(bucket.close)
            assert not close_future.done()

            allow_download.set()
            download_path = download_future.result()
            assert download_path.parent == temp_dir
            close_future.result()

        assert not temp_dir.exists()

    def test_with_prefix(self, s3_client) -> None:
        bucket = S3Bucket("test-bucket", "prefix/", s3_client=s3_client)
        child = bucket.with_prefix("sub/")
        child.put_bytes(b"data", "file.txt")
        assert child.check_file_exists("file.txt")
        assert bucket.check_file_exists("sub/file.txt")

    def test_concurrent_downloads_success(self, s3_client, mocker: MockerFixture) -> None:
        download_started = threading.Event()
        allow_download = threading.Event()
        old_download_file = s3_client.download_file

        def mock_download_file(*args, **kwargs):
            download_started.set()
            allow_download.wait()
            return old_download_file(*args, **kwargs)

        mocker.patch.object(s3_client, "download_file", side_effect=mock_download_file)

        bucket = S3Bucket("test-bucket", s3_client=s3_client)
        remote_path = "concurrent.txt"
        local_bytes = b"concurrent data"
        bucket.put_bytes(local_bytes, remote_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(bucket.get_file, remote_path) for _ in range(5)]

            download_started.wait()
            time.sleep(0.05)
            allow_download.set()

            for future in futures:
                assert future.result().read_bytes() == local_bytes
        assert cast(mocker.MagicMock, s3_client.download_file).call_count == 5

    def test_concurrent_downloads_exception(self, s3_client, mocker: MockerFixture) -> None:
        download_started = threading.Event()
        allow_download = threading.Event()
        error = Exception("Network failure.")

        def mock_download_file(*args, **kwargs):
            download_started.set()
            allow_download.wait()
            raise error

        mocker.patch.object(s3_client, "download_file", side_effect=mock_download_file)

        bucket = S3Bucket("test-bucket", s3_client=s3_client)
        remote_path = "error.txt"

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(bucket.get_file, remote_path) for _ in range(5)]

            download_started.wait()
            time.sleep(0.05)
            allow_download.set()

            for future in futures:
                with pytest.raises(Exception) as exc_info:
                    future.result()
                assert exc_info.value is error
        assert cast(mocker.MagicMock, s3_client.download_file).call_count == 5

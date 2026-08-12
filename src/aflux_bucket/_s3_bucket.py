import io
import threading
from collections.abc import Iterator
from concurrent.futures import Future
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Self, override

import boto3
import botocore.exceptions

from ._file_allocator import FileAllocator
from ._protocol import Bucket
from ._types import BucketFileMeta

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client
else:
    S3Client = object


class S3Bucket(Bucket):
    def __init__(
        self,
        bucket_name: str,
        bucket_prefix: str = "",
        *,
        temp_dir: str | Path | FileAllocator | None = None,
        s3_client: S3Client | None = None,
    ):
        self._bucket_name = bucket_name
        self._bucket_prefix = bucket_prefix
        self._allocator = temp_dir if isinstance(temp_dir, FileAllocator) else FileAllocator(temp_dir)

        if s3_client is None:
            s3_client = boto3.client("s3")
        self._s3_client = s3_client

        self._registry_lock = threading.Lock()
        self._active_download_map: dict[str, Future[Path]] = {}
        self._closed = False

    def _ensure_open(self) -> None:
        if not self._closed:
            return
        msg = "S3Bucket is closed."
        raise RuntimeError(msg)

    def _get_bucket_path(self, remote_path: str) -> str:
        return f"{self._bucket_prefix}{remote_path}"

    @override
    def check_file_exists(self, remote_path: str) -> bool:
        self._ensure_open()
        bucket_key = self._get_bucket_path(remote_path)
        try:
            self._s3_client.head_object(Bucket=self._bucket_name, Key=bucket_key)
            return True
        except botocore.exceptions.ClientError as e:
            if int(e.response["Error"]["Code"]) != 404:
                raise
            return False

    @override
    def get_file_meta(self, remote_path: str) -> BucketFileMeta:
        self._ensure_open()
        bucket_key = self._get_bucket_path(remote_path)
        resp = self._s3_client.head_object(Bucket=self._bucket_name, Key=bucket_key)
        last_modified = resp["LastModified"]
        size = resp["ContentLength"]
        return BucketFileMeta(path=remote_path, size=size, last_modified=last_modified)

    @override
    def get_file_metas(self, remote_prefix: str = "") -> Iterator[BucketFileMeta]:
        self._ensure_open()
        bucket_prefix = self._get_bucket_path(remote_prefix)
        paginator = self._s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket_name, Prefix=bucket_prefix):
            for obj in page.get("Contents", []):
                file_meta = BucketFileMeta(
                    path=obj["Key"].removeprefix(self._bucket_prefix),
                    size=obj["Size"],
                    last_modified=obj["LastModified"],
                )
                yield file_meta

    @override
    def get_file(self, remote_path: str) -> Path:
        with self._registry_lock:
            self._ensure_open()
            temp_file = self._allocator.allocate(remote_path)
            future = Future()
            self._active_download_map[temp_file.name] = future

        try:
            bucket_key = self._get_bucket_path(remote_path)
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            self._s3_client.download_file(self._bucket_name, bucket_key, str(temp_file))
        except BaseException as e:
            with self._registry_lock:
                self._active_download_map.pop(temp_file.name, None)
                future.set_exception(e)
            raise
        else:
            with self._registry_lock:
                self._active_download_map.pop(temp_file.name, None)
                future.set_result(temp_file)
            return temp_file

    @override
    def get_bytes(self, remote_path: str) -> bytes:
        self._ensure_open()
        bucket_key = self._get_bucket_path(remote_path)
        buffer = io.BytesIO()
        self._s3_client.download_fileobj(self._bucket_name, bucket_key, buffer)
        return buffer.getvalue()

    @override
    def put_file(self, local_file: str | Path, remote_path: str) -> None:
        self._ensure_open()
        bucket_key = self._get_bucket_path(remote_path)
        self._s3_client.upload_file(str(local_file), self._bucket_name, bucket_key)

    @override
    def put_bytes(self, local_bytes: bytes, remote_path: str) -> None:
        self._ensure_open()
        bucket_key = self._get_bucket_path(remote_path)
        self._s3_client.upload_fileobj(io.BytesIO(local_bytes), self._bucket_name, bucket_key)

    @override
    def delete_file(self, remote_path: str) -> None:
        self._ensure_open()
        bucket_key = self._get_bucket_path(remote_path)
        self._s3_client.delete_object(Bucket=self._bucket_name, Key=bucket_key)

    @override
    def with_prefix(self, remote_prefix: str) -> "S3Bucket":
        self._ensure_open()
        return S3Bucket(
            self._bucket_name,
            self._get_bucket_path(remote_prefix),
            temp_dir=self._allocator.make_child(),
            s3_client=self._s3_client,
        )

    def clear_temp_dir(self) -> None:
        self._ensure_open()
        self._allocator.clear()

    def close(self) -> None:
        with self._registry_lock:
            if self._closed:
                return
            self._closed = True
            active_futures = list(self._active_download_map.values())

        for future in active_futures:
            future.exception()

        self._allocator.close()

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

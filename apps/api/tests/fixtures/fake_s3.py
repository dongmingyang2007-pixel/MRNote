"""A minimal boto3-compatible fake S3 client for tests.

Implements only the surface used by the ai_action_logger:
``head_bucket``, ``create_bucket``, ``put_object``, ``get_object``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import ClientError


@dataclass
class _StoredObject:
    body: bytes
    content_type: str


def _client_error(code: str, message: str, op_name: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        op_name,
    )


@dataclass
class FakeS3Client:
    _store: dict[tuple[str, str], _StoredObject] = field(default_factory=dict)
    _buckets: set[str] = field(default_factory=set)

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]:
        if Bucket not in self._buckets:
            raise _client_error("404", "Not Found", "HeadBucket")
        return {}

    def create_bucket(self, *, Bucket: str, **_: Any) -> dict[str, Any]:
        self._buckets.add(Bucket)
        return {"Location": f"/{Bucket}"}

    def put_object(
        self, *, Bucket: str, Key: str, Body: Any,
        ContentType: str = "application/octet-stream", **_: Any,
    ) -> dict[str, Any]:
        if Bucket not in self._buckets:
            raise _client_error("NoSuchBucket", f"bucket {Bucket} missing", "PutObject")
        if isinstance(Body, (bytes, bytearray)):
            data = bytes(Body)
        elif isinstance(Body, str):
            data = Body.encode("utf-8")
        else:
            data = Body.read()
        self._store[(Bucket, Key)] = _StoredObject(body=data, content_type=ContentType)
        return {"ETag": f'"{len(data)}"'}

    def get_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:
        obj = self._store.get((Bucket, Key))
        if obj is None:
            raise _client_error("NoSuchKey", f"{Bucket}/{Key} missing", "GetObject")
        return {
            "Body": io.BytesIO(obj.body),
            "ContentType": obj.content_type,
            "ContentLength": len(obj.body),
        }

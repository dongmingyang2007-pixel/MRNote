from botocore.exceptions import ClientError
import pytest

from tests.fixtures.fake_s3 import FakeS3Client


def test_put_and_get_roundtrip() -> None:
    client = FakeS3Client()
    client.create_bucket(Bucket="b1")
    client.put_object(Bucket="b1", Key="k1", Body=b"hello", ContentType="application/json")

    resp = client.get_object(Bucket="b1", Key="k1")
    assert resp["Body"].read() == b"hello"
    assert resp["ContentType"] == "application/json"


def test_head_bucket_404_when_missing() -> None:
    client = FakeS3Client()
    with pytest.raises(ClientError) as exc:
        client.head_bucket(Bucket="nope")
    assert exc.value.response["Error"]["Code"] == "404"


def test_get_object_missing_key() -> None:
    client = FakeS3Client()
    client.create_bucket(Bucket="b1")
    with pytest.raises(ClientError) as exc:
        client.get_object(Bucket="b1", Key="absent")
    assert exc.value.response["Error"]["Code"] == "NoSuchKey"

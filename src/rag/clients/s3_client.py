from __future__ import annotations

import boto3

from config import get_settings


class S3Client:
    """Object storage access for raw documents and index snapshots."""

    def __init__(self) -> None:
        s = get_settings()
        self._raw_bucket = s.s3_raw_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
        )

    def list_documents(self, tenant_id: str) -> list[str]:
        prefix = f"{tenant_id}/"
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._raw_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._raw_bucket, Key=key)
        return resp["Body"].read()

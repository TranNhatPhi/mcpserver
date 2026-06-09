"""MinIO / S3-compatible storage tools for the MCP server.

Reads files directly from a MinIO bucket (or any S3-compatible endpoint).
Team members upload/update files via the MinIO web console (port 9001) or
the `mc` CLI — the server picks up changes immediately on the next call,
no restart needed.

Environment variables:
    MCP_S3_ENDPOINT    e.g. http://minio:9000 or https://s3.amazonaws.com
    MCP_S3_ACCESS_KEY
    MCP_S3_SECRET_KEY
    MCP_S3_BUCKET      bucket name (default: brainlnc)
    MCP_S3_REGION      (default: us-east-1)
"""

import io
import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

_ENDPOINT = os.environ.get("MCP_S3_ENDPOINT", "http://minio:9000")
_ACCESS_KEY = os.environ.get("MCP_S3_ACCESS_KEY", "admin")
_SECRET_KEY = os.environ.get("MCP_S3_SECRET_KEY", "password123")
_BUCKET = os.environ.get("MCP_S3_BUCKET", "brainlnc")
_REGION = os.environ.get("MCP_S3_REGION", "us-east-1")

_client = None


def _s3():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
            region_name=_REGION,
            config=Config(signature_version="s3v4"),
        )
    return _client


def s3_list(prefix: str = "") -> str:
    """List files in the MinIO bucket under an optional prefix (folder path).

    Examples:
        s3_list()              → list everything in the bucket root
        s3_list("brainkichban") → list files in the brainkichban folder
    """
    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET, Prefix=prefix, Delimiter="/")

        folders, files = [], []
        for page in pages:
            for cp in page.get("CommonPrefixes") or []:
                folders.append("  dir   " + cp["Prefix"])
            for obj in page.get("Contents") or []:
                size = obj["Size"]
                folders_or_files = files if not obj["Key"].endswith("/") else folders
                folders_or_files.append(f"  file  {size:>10,}  {obj['Key']}")

        lines = folders + files
        if not lines:
            loc = f"{_BUCKET}/{prefix}" if prefix else _BUCKET
            return f"(empty: {loc})"
        return f"Bucket: {_BUCKET}/{prefix}\n" + "\n".join(lines)
    except ClientError as e:
        return f"S3 error: {e}"


def s3_read(key: str) -> str:
    """Read a text file from the MinIO bucket by its key (path).

    Example:
        s3_read("brainkichban/01_Company_Brain.md")
    """
    MAX_CHARS = 500_000
    try:
        obj = _s3().get_object(Bucket=_BUCKET, Key=key)
        body = obj["Body"].read()
        text = body.decode("utf-8", errors="replace")
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + f"\n...[truncated at {MAX_CHARS} chars]"
        return text
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchKey":
            return f"File not found in bucket '{_BUCKET}': {key}"
        return f"S3 error: {e}"


def s3_search(pattern: str, prefix: str = "") -> str:
    """Search for text across all files in the MinIO bucket.

    Args:
        pattern: substring to search for (case-insensitive)
        prefix:  optional folder prefix to limit the search
    """
    MAX_RESULTS = 50
    needle = pattern.lower()
    results = []

    try:
        paginator = _s3().get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=_BUCKET, Prefix=prefix)

        for page in pages:
            for obj in page.get("Contents") or []:
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                # Only search text files
                ext = os.path.splitext(key)[1].lower()
                if ext not in {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html"}:
                    continue
                try:
                    body = _s3().get_object(Bucket=_BUCKET, Key=key)["Body"].read()
                    text = body.decode("utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if needle in line.lower():
                            results.append(f"{key}:{i}: {line.strip()}")
                            if len(results) >= MAX_RESULTS:
                                break
                except ClientError:
                    continue
                if len(results) >= MAX_RESULTS:
                    break
            if len(results) >= MAX_RESULTS:
                break

    except ClientError as e:
        return f"S3 error: {e}"

    if not results:
        return f"No matches for '{pattern}' in bucket {_BUCKET}/{prefix}"
    suffix = " (truncated)" if len(results) >= MAX_RESULTS else ""
    return f"Found {len(results)} match(es){suffix}:\n" + "\n".join(results)

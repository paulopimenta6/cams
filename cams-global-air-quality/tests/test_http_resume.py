import hashlib
import json
from pathlib import Path

from cams_air_quality.downloader import download_range


class Response:
    def __init__(self, status, headers, data):
        self.status_code = status
        self.headers = headers
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.data


def test_range_resume(tmp_path, monkeypatch):
    url = "https://example.invalid/asset"
    p = tmp_path / "asset.part"
    p.write_bytes(b"abc")
    Path(str(p) + ".json").write_text(
        json.dumps(
            {
                "asset_sha256": hashlib.sha256(url.encode()).hexdigest(),
                "expected": 6,
                "etag": '"v1"',
            }
        )
    )

    def get(url, headers, **kwargs):
        assert headers["Range"] == "bytes=3-"
        assert headers["If-Range"] == '"v1"'
        return Response(206, {"Content-Range": "bytes 3-5/6", "ETag": '"v1"'}, b"def")

    monkeypatch.setattr("cams_air_quality.downloader.requests.get", get)
    download_range(url, p, 6, 10)
    assert p.read_bytes() == b"abcdef"


def test_range_not_supported_restarts(tmp_path, monkeypatch):
    url = "https://example.invalid/asset"
    p = tmp_path / "asset.part"
    p.write_bytes(b"abc")
    Path(str(p) + ".json").write_text(
        json.dumps({"asset_sha256": hashlib.sha256(url.encode()).hexdigest(), "expected": 6})
    )
    monkeypatch.setattr(
        "cams_air_quality.downloader.requests.get", lambda *a, **k: Response(200, {}, b"abcdef")
    )
    download_range(url, p, 6, 10)
    assert p.read_bytes() == b"abcdef"


def test_changed_signed_asset_restarts(tmp_path, monkeypatch):
    p = tmp_path / "asset.part"
    p.write_bytes(b"old")
    Path(str(p) + ".json").write_text(json.dumps({"asset_sha256": "old", "expected": 6}))

    def get(url, headers, **kwargs):
        assert "Range" not in headers
        return Response(200, {}, b"abcdef")

    monkeypatch.setattr("cams_air_quality.downloader.requests.get", get)
    download_range("https://example.invalid/new", p, 6, 10)
    assert p.read_bytes() == b"abcdef"

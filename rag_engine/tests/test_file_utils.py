"""file_utils 单元测试：扩展名校验、流式保存（哈希 / 重名 / 超限清理）"""
import asyncio
import hashlib

import pytest
from fastapi import HTTPException

from utils.file_utils import save_upload, validate_extension

ALLOWED = [".txt", ".pdf", ".md", ".docx", ".xlsx"]


class FakeUploadFile:
    """模拟 FastAPI UploadFile：测试只需要 filename 与异步 read()"""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        chunk = self._content[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


def run(coro):
    """在同步测试里执行协程（避免额外引入 pytest-asyncio 依赖）"""
    return asyncio.run(coro)


class TestValidateExtension:
    def test_accepts_allowed(self):
        assert validate_extension("员工手册.pdf", ALLOWED) == ".pdf"

    def test_lowercases_extension(self):
        assert validate_extension("REPORT.PDF", ALLOWED) == ".pdf"

    def test_rejects_disallowed(self):
        with pytest.raises(HTTPException) as exc:
            validate_extension("archive.zip", ALLOWED)
        assert exc.value.status_code == 400

    def test_rejects_missing_extension(self):
        with pytest.raises(HTTPException) as exc:
            validate_extension("README", ALLOWED)
        assert exc.value.status_code == 400


class TestSaveUpload:
    def test_saves_content_and_returns_sha256(self, tmp_path):
        content = "你好，世界".encode("utf-8") * 100

        path, file_hash = run(
            save_upload(FakeUploadFile("a.txt", content), str(tmp_path), 10 * 1024 * 1024)
        )

        assert path.name == "a.txt"
        assert path.read_bytes() == content
        assert file_hash == hashlib.sha256(content).hexdigest()

    def test_renames_when_same_name_exists(self, tmp_path):
        content = b"hello"

        first, _ = run(save_upload(FakeUploadFile("a.txt", content), str(tmp_path), 1024))
        second, _ = run(save_upload(FakeUploadFile("a.txt", content), str(tmp_path), 1024))

        assert first.name == "a.txt"
        assert second.name == "a (1).txt"
        assert first.read_bytes() == second.read_bytes() == content

    def test_rejects_oversize_and_cleans_up(self, tmp_path):
        content = b"x" * (3 * 1024 * 1024)   # 3MB，限制 1MB

        with pytest.raises(HTTPException) as exc:
            run(save_upload(FakeUploadFile("big.txt", content), str(tmp_path), 1024 * 1024))

        assert exc.value.status_code == 413
        # 超限时必须清理掉写到一半的文件，不留残留
        assert list(tmp_path.iterdir()) == []

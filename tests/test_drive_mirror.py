"""drive_mirror: 머리말·건너뜀·업로드 요청 모양을 네트워크 없이 확인한다."""
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import drive_mirror as dm  # noqa: E402

MD = "# 브리핑 묶음 — 생성 2026-11-25 09:30 KST\n런/발표: ECMWF 11-24 12z\n\n## 특보 현황\n- 건조 주의\n"
KST = dt.timezone(dt.timedelta(hours=9))


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code, self._p = code, payload or {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Session:
    def __init__(self, meta):
        self.meta, self.patches = meta, []

    def get(self, url, **kw):
        return self.meta

    def patch(self, url, **kw):
        self.patches.append((url, kw))
        return _Resp(200, {"id": "f", "name": "n", "mimeType": dm.GDOC})


class DriveMirrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "latest.md")
        Path(self.path).write_text(MD, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_stamp_and_header_point_to_hourly_file(self):
        self.assertEqual(dm.source_stamp(MD), "2026112509")
        out = dm.build_payload(MD, dt.datetime(2026, 11, 25, 9, 41, tzinfo=KST))
        self.assertIn("briefing/2026112509.md", out.splitlines()[0])
        self.assertIn("사본 갱신 2026-11-25 09:41 KST", out.splitlines()[0])
        self.assertTrue(out.endswith(MD))

    def test_unchanged_content_is_not_uploaded(self):
        s = _Session(_Resp(200, {"name": "n", "mimeType": dm.GDOC, "appProperties": {"src_sha": dm.content_hash(MD)}}))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(dm.mirror(self.path, "", "FID", session=s, token="t"), "skipped")
        self.assertEqual(s.patches, [])

    def test_changed_content_uploads_multipart_with_hash(self):
        s = _Session(_Resp(200, {"name": "n", "mimeType": dm.GDOC, "appProperties": {"src_sha": "old"}}))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(dm.mirror(self.path, "", "FID", session=s, token="t",
                                       now_kst=dt.datetime(2026, 11, 25, 9, 41, tzinfo=KST)), "updated")
        url, kw = s.patches[0]
        self.assertTrue(url.endswith("/upload/drive/v3/files/FID"))
        self.assertEqual(kw["params"]["uploadType"], "multipart")
        body = kw["data"].decode("utf-8")
        meta = json.loads(body.split("\r\n\r\n", 1)[1].split("\r\n", 1)[0])
        self.assertEqual(meta["appProperties"], {"src_sha": dm.content_hash(MD), "src_stamp": "2026112509"})
        self.assertIn("text/plain", body)
        self.assertIn("## 특보 현황", body)

    def test_missing_file_gives_actionable_error(self):
        s = _Session(_Resp(404))
        with self.assertRaises(SystemExit) as cm:
            dm.mirror(self.path, "", "FID", session=s, token="t")
        self.assertIn("편집자", str(cm.exception))

    def test_unconfigured_run_is_a_noop_success(self):
        env = {k: os.environ.pop(k) for k in ("GDRIVE_SA_JSON", "GDRIVE_FILE_ID") if k in os.environ}
        try:
            with redirect_stdout(io.StringIO()) as buf:
                self.assertEqual(dm.main(["x", self.path]), 0)
            self.assertIn("미설정", buf.getvalue())
        finally:
            os.environ.update(env)


if __name__ == "__main__":
    unittest.main()

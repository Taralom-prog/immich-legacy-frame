"""Tests. Run with: python3 -m unittest discover tests"""
import http.client
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import server  # noqa: E402


class DurationTests(unittest.TestCase):
    def test_milliseconds(self):
        self.assertEqual(server.duration_seconds(10535), 10.535)

    def test_legacy_string(self):
        self.assertAlmostEqual(server.duration_seconds("0:01:02.500"), 62.5)

    def test_missing_or_garbage(self):
        self.assertEqual(server.duration_seconds(None), 0.0)
        self.assertEqual(server.duration_seconds("nope"), 0.0)


class DateTests(unittest.TestCase):
    def test_english(self):
        self.assertEqual(server.format_date("2023-07-14T15:32:10.000Z", "en"), "14 July 2023")

    def test_french_first_of_month(self):
        self.assertEqual(server.format_date("2024-10-01T00:00:00.000Z", "fr"), "1er octobre 2024")

    def test_invalid(self):
        self.assertEqual(server.format_date(None), "")
        self.assertEqual(server.format_date("2024-13-01"), "")
        self.assertEqual(server.format_date("2024-02-31"), "")


class PlaceTests(unittest.TestCase):
    def test_fallbacks(self):
        self.assertEqual(server.place_name({"city": "Lyon", "country": "France"}), "Lyon")
        self.assertEqual(server.place_name({"city": " ", "state": "Bretagne"}), "Bretagne")
        self.assertEqual(server.place_name({"country": "France"}), "France")
        self.assertEqual(server.place_name(None), "")


class RangeTests(unittest.TestCase):
    def test_no_header(self):
        self.assertIsNone(server.parse_range(None, 100))

    def test_open_ended(self):
        self.assertEqual(server.parse_range("bytes=0-", 100), (0, 99))

    def test_bounded_and_clamped(self):
        self.assertEqual(server.parse_range("bytes=10-19", 100), (10, 19))
        self.assertEqual(server.parse_range("bytes=90-500", 100), (90, 99))

    def test_suffix(self):
        self.assertEqual(server.parse_range("bytes=-10", 100), (90, 99))

    def test_unsatisfiable(self):
        self.assertEqual(server.parse_range("bytes=200-", 100), "invalid")

    def test_unsupported_forms_are_ignored(self):
        self.assertIsNone(server.parse_range("bytes=0-1,5-6", 100))
        self.assertIsNone(server.parse_range("bytes=-", 100))
        self.assertIsNone(server.parse_range("bytes=5-3", 100))


class FfmpegCommandTests(unittest.TestCase):
    def test_targets_old_devices(self):
        cmd = server.ffmpeg_command("in.mov", "out.mp4")
        self.assertIn("main", cmd)
        self.assertIn("3.1", cmd)
        self.assertEqual(cmd[-1], "out.mp4")

    def test_scale_box_respects_level_3_1(self):
        # 1280x720 box: 80 x 45 = 3,600 macroblocks, the level 3.1 maximum
        f = server.scale_filter(1280)
        self.assertIn("if(gte(iw,ih),1280,720)", f)
        self.assertIn("if(gte(iw,ih),720,1280)", f)


class EnvTests(unittest.TestCase):
    def test_trailing_comment_is_ignored(self):
        with mock.patch.dict(os.environ, {"X": "true   # a comment", "N": "12 # twelve"}):
            self.assertTrue(server.env_bool("X", False))
            self.assertEqual(server.env_int("N", 0), 12)

    def test_bad_values_exit_with_a_message(self):
        with mock.patch.dict(os.environ, {"X": "maybe", "N": "ten"}):
            with self.assertRaises(SystemExit):
                server.env_bool("X", False)
            with self.assertRaises(SystemExit):
                server.env_int("N", 0)


class LogTextTests(unittest.TestCase):
    def test_no_line_injection(self):
        self.assertEqual(server.clean_log_text("a\nFAKE line\r"), "a FAKE line ")


ASSET = "11111111-2222-4333-8444-555555555555"
OTHER = "99999999-2222-4333-8444-555555555555"


class HttpTests(unittest.TestCase):
    """The HTTP layer, with a temporary cache folder and no Immich."""

    @classmethod
    def setUpClass(cls):
        cls.cache = tempfile.mkdtemp()
        cls.patch = mock.patch.object(server, "CACHE_DIR", cls.cache)
        cls.patch.start()
        with open(server.cache_path(ASSET), "wb") as f:
            f.write(bytes(range(100)))
        server.served_ids.add(ASSET)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.patch.stop()
        shutil.rmtree(cls.cache)

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_page_gets_its_config(self):
        resp, body = self.get("/")
        self.assertEqual(resp.status, 200)
        self.assertNotIn(b"/*CONFIG*/{}", body)
        self.assertIn(b'"photoSeconds"', body)

    def test_whole_video(self):
        resp, body = self.get(f"/vid/{ASSET}")
        self.assertEqual(resp.status, 200)
        self.assertEqual(len(body), 100)

    def test_video_range(self):
        resp, body = self.get(f"/vid/{ASSET}", {"Range": "bytes=10-19"})
        self.assertEqual(resp.status, 206)
        self.assertEqual(resp.getheader("Content-Range"), "bytes 10-19/100")
        self.assertEqual(body, bytes(range(10, 20)))

    def test_unsatisfiable_range(self):
        resp, _ = self.get(f"/vid/{ASSET}", {"Range": "bytes=500-"})
        self.assertEqual(resp.status, 416)

    def test_only_served_assets_are_reachable(self):
        for path in (f"/vid/{OTHER}", f"/img/{OTHER}", f"/thumb/{OTHER}", "/img/../../etc/passwd"):
            resp, _ = self.get(path)
            self.assertEqual(resp.status, 404, path)

    def test_log_beacon(self):
        resp, body = self.get("/log?m=hello")
        self.assertEqual(resp.status, 204)
        self.assertEqual(body, b"")


class BatchTests(unittest.TestCase):
    def test_unconverted_videos_are_skipped(self):
        assets = [
            {"id": ASSET, "type": "IMAGE", "localDateTime": "2024-10-29T10:00:00.000Z",
             "exifInfo": {"city": "Lyon"}},
            {"id": OTHER, "type": "VIDEO", "duration": 5000},
        ]
        with tempfile.TemporaryDirectory() as cache, \
                mock.patch.object(server, "CACHE_DIR", cache), \
                mock.patch.object(server, "immich_json", return_value=assets):
            batch = server.random_batch(10)
        self.assertEqual([item["id"] for item in batch], [ASSET])
        self.assertEqual(batch[0]["date"], "29 October 2024")
        self.assertEqual(batch[0]["place"], "Lyon")


if __name__ == "__main__":
    unittest.main()

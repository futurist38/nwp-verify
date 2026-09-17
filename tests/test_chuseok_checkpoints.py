import datetime as dt
import unittest

import chuseok_track as c


class CheckpointMergeTest(unittest.TestCase):
    def test_uses_latest_mid_then_short_at_05_11_17(self):
        def record(kind, key, value, has_target=True):
            days = {"20260925": {"tmax": value, "tmin": value - 10, "sky": "맑음", "pop": 0, "src": kind}} if has_target else {}
            return {"kind": kind, "issue_key": key, "issue": key,
                    "cities": {city: days for city in c.CITIES}}

        records = [record("mid", "2026091618", 20), record("short", "2026091705", 0, False),
                   record("mid", "2026091706", 22), record("short", "2026091711", 0, False),
                   record("short", "2026091717", 24)]
        start = dt.datetime(2026, 9, 16, 17, tzinfo=c.KST)
        now = dt.datetime(2026, 9, 17, 17, 20, tzinfo=c.KST)

        rows = c.merge(records, now, start)["cities"]["서울"]["20260925"]

        self.assertEqual([x["issue"] for x in rows], ["2026091705", "2026091711", "2026091717"])
        self.assertEqual([x["tmax"] for x in rows], [20, 22, 24])
        self.assertEqual([x["source_issue"] for x in rows], ["2026091618", "2026091706", "2026091717"])


if __name__ == "__main__":
    unittest.main()

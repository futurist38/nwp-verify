import unittest

import chuseok_track as c


class CheckpointMergeTest(unittest.TestCase):
    def test_switches_from_mid_issues_to_short_issues(self):
        def record(kind, key, value, has_target=True):
            days = {"20260925": {"tmax": value, "tmin": value - 10, "sky": "맑음", "pop": 0, "src": kind}} if has_target else {}
            if kind == "mid" and has_target:
                days["20260926"] = {**days["20260925"]}
            return {"kind": kind, "issue_key": key, "issue": key,
                    "cities": {city: days for city in c.CITIES}}

        records = [record("mid", "2026091618", 20), record("short", "2026091705", 0, False),
                   record("mid", "2026091706", 22), record("short", "2026091711", 0, False),
                   record("mid", "2026091718", 23), record("short", "2026091805", 24),
                   record("mid", "2026091806", 25), record("short", "2026091811", 26)]

        merged = c.merge(records)
        rows = merged["cities"]["서울"]["20260925"]

        self.assertEqual([x["issue"] for x in rows],
                         ["2026091618", "2026091706", "2026091718", "2026091805", "2026091811"])
        self.assertEqual([x["tmax"] for x in rows], [20, 22, 23, 24, 26])
        fallback = merged["cities"]["서울"]["20260926"]
        self.assertEqual([x["tmax"] for x in fallback], [20, 22, 23, 23, 25])


if __name__ == "__main__":
    unittest.main()

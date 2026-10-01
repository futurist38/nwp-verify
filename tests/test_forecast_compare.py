import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import importlib.util
import types

import forecast_compare as fc


class ForecastComparisonTests(unittest.TestCase):
    def setUp(self):
        self.day = "20261002"
        self.raw = {"서울": {f"{self.day}{h:02d}": 10+h/2 for h in range(24)}}
        for cat, value in (("SKY", 1), ("PTY", 0), ("POP", 0)):
            self.raw["서울#"+cat] = {f"{self.day}{h:02d}": value for h in range(24)}

    def record(self, raw=None):
        return fc.normalize_short("2026100105", raw or self.raw)["cities"]["서울"][self.day]

    def test_full_day_extrema_and_official_priority(self):
        self.assertEqual(self.record()["tmax"], {"value": 21.5, "basis": "TMP24"})
        self.raw["서울#TMX"] = {self.day+"15": 23}
        self.raw["서울#TMN"] = {self.day+"06": 8}
        self.assertEqual(self.record()["tmax"], {"value": 23, "basis": "TMX"})
        self.assertEqual(self.record()["tmin"], {"value": 8, "basis": "TMN"})

    def test_partial_or_invalid_hours_never_become_daily_extrema(self):
        for value in (None, -999, float("nan"), "bad"):
            raw=copy.deepcopy(self.raw)
            raw["서울"][self.day+"00"] = value
            self.assertIsNone(self.record(raw)["tmax"])
            self.assertIsNone(self.record(raw)["tmin"])

    def test_weather_requires_all_twelve_hours(self):
        self.raw["서울#PTY"].pop(self.day+"00")
        rec=self.record()
        self.assertIsNone(rec["wx_am"])
        self.assertEqual(rec["wx_pm"]["key"], "clear|")

    def test_sky_mode_tie_and_rain_match_medium_semantics(self):
        for h in range(6):
            self.raw["서울#SKY"][f"{self.day}{h:02d}"]=4
        self.raw["서울#PTY"][self.day+"03"]=1
        short=self.record()["wx_am"]
        mid=fc.mid_weather("흐리고 비",40)
        self.assertEqual(short["key"],mid["key"])
        self.assertEqual(short["code"],"rain")
        self.assertEqual(fc.mid_weather("구름많고 눈",30)["key"],"partly|눈")
        self.assertIsNone(fc.mid_weather("알 수 없음",0))

    def test_daily_medium_weather_is_not_split_into_half_days(self):
        d=fc.normalize_mid("2026100106",{}, {"11B00000":{"wf8":"맑음","rnSt8":10}})
        rec=d["cities"]["서울"]["20261009"]
        self.assertIsNone(rec["wx_am"])
        self.assertIsNone(rec["wx_pm"])
        self.assertEqual(rec["wx_day"]["code"],"clear")

    def test_partial_mid_temperature_keeps_weather(self):
        d=fc.normalize_mid("2026100106",{}, {"_temperatures":{"서울":{"20261005":{"min":12,"max":24}}},
                                              "11B00000":{"wf4Am":"맑음","wf4Pm":"흐림"}})
        rec=d["cities"]["서울"]["20261005"]
        self.assertEqual(rec["tmax"]["value"],24)
        self.assertIsNotNone(rec["wx_pm"])

    def test_merge_cannot_regress_official_or_filled_weather(self):
        hourly={"tmax":{"value":20,"basis":"TMP24"},"wx_am":None}
        official={"tmax":{"value":22,"basis":"TMX"},"wx_am":{"key":"clear|"}}
        self.assertEqual(fc.merge(hourly,official),official)
        self.assertEqual(fc.merge(official,hourly),official)
        self.assertEqual(fc.merge(official,{"tmax":{"value":23,"basis":"TMX"}}),official)

    def test_export_preserves_old_published_issue_and_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            verif=Path(tmp)/"verification"; site=Path(tmp)/"site"
            fc.write(verif/"kmafcst"/"20261001.json",{"2026100105":self.raw})
            entries=fc.export(site,verif,archive=True)
            self.assertEqual(entries[0]["temperature_cities"],["서울"])
            docpath=site/"forecast_compare"/entries[0]["file"]
            original=docpath.read_bytes()
            (verif/"kmafcst"/"20261001.json").unlink()
            (verif/"forecast_compare"/"2026100105-short.json").unlink()
            second=fc.export(site,verif)
            self.assertEqual(docpath.read_bytes(),original)
            self.assertEqual(entries,second)

    def test_short_api_pagination_does_not_drop_later_forecast_dates(self):
        requests=types.ModuleType("requests")
        def response(hour, val):
            r=Mock()
            r.json.return_value={"response":{"header":{"resultCode":"00"},"body":{
                "totalCount":2,"items":{"item":[{"category":"TMP","fcstDate":"20261002","fcstTime":hour,"fcstValue":val}]}}}}
            return r
        requests.get=Mock(side_effect=[response("0000","10"),response("2300","20")])
        with patch.dict("sys.modules",{"requests":requests,"sslfix":types.ModuleType("sslfix")}):
            spec=importlib.util.spec_from_file_location("vilage_test",Path(__file__).parents[1]/"kma_vilage.py")
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            result=module.fetch(60,127,"2026100105","test-key",retries=1)
        self.assertEqual(result["TMP"],{"2026100200":10.0,"2026100223":20.0})
        self.assertEqual([call.kwargs["params"]["pageNo"] for call in requests.get.call_args_list],[1,2])


if __name__ == "__main__":
    unittest.main()

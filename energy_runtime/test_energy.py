import unittest,datetime as dt
from unittest.mock import patch
from energy_data import number,weighted,parse_short,minute_minimum,WEIGHTS
from energy_publication import publication_label
from build_energy import state_from

class EnergyTests(unittest.TestCase):
    def test_negative_winter_temperature_and_rounding(self):
        self.assertEqual(number('-9.0'),-9)
        self.assertEqual(weighted(dict.fromkeys(WEIGHTS,1.25)),1.3)
        self.assertEqual(weighted(dict.fromkeys(WEIGHTS,-1.25)),-1.3)
        with self.assertRaises(ValueError):number('-99')
        with self.assertRaises(ValueError):weighted({'서울':3})
    def test_city_short_exact_issue(self):
        raw='11B10101,202610290500,202610291200,A02,1,109,0,0,0,0,0,0,13,60,DB04,1,흐리고 가끔 비\n11B10101,202610290800,202610291200,A02,1,109,0,0,0,0,0,0,15,60,DB04,1,비'
        result=parse_short(raw,'2026102905')
        self.assertEqual(result['서울']['2026-10-29']['pm']['temperature'],13)
    def test_minimum_excludes_after_07(self):
        lines=['# YYMMDDHHMI STN TA']
        start=dt.datetime(2026,10,29)
        for n in range(422):
            tm=start+dt.timedelta(minutes=n);lines.append(f'{tm:%Y%m%d%H%M} 108 '+('-20' if n==421 else '5'))
        with patch('energy_data.request',return_value='\n'.join(lines)):
            c,v,meta=minute_minimum('서울',start.date())
        self.assertEqual(v,5);self.assertEqual(meta['last'],'202610290700')
    def test_missing_observations_fail(self):
        with patch('energy_data.request',return_value='# YYMMDDHHMI STN TA\n202610290700 108 3'):
            with self.assertRaises(ValueError):minute_minimum('서울',dt.date(2026,10,29))
    def test_timestamp_and_weather(self):
        self.assertEqual(publication_label('2026-10-29T22:00:00+00:00'),'발표시점: 2026. 10. 30.(금) 07시 기준')
        self.assertIsNone(state_from('흐리고 비')['frequency'])
        self.assertEqual(state_from('흐리고 때때로 비')['frequency'],'가끔')

if __name__=='__main__':unittest.main()

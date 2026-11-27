import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ingest_dashboard as mod

class Slots(unittest.TestCase):
    def run_export(self, events, at='2026-11-11T19:30:00+09:00'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); event_dir=root/'events'; event_dir.mkdir()
            for i,e in enumerate(events):
                (event_dir/f'{i}.json').write_text(json.dumps(e))
            with patch.object(mod,'EVENT_DIR',event_dir):
                return mod.export(tmp,now=dt.datetime.fromisoformat(at))
    def event(self, start, end, source='kma_short', status='success'):
        return dict(source=source,label=source,status=status,started_kst=f'2026-11-11T{start}:00+09:00',ended_kst=f'2026-11-11T{end}:00+09:00')
    def test_states(self):
        j=self.run_export([self.event('05:25','05:40')])
        m=j['matrix']['kma_short']
        self.assertEqual(m['2026-11-11T05:00+09:00'],'success')
        self.assertEqual(m['2026-11-11T11:00+09:00'],'missed')
        self.assertEqual(m['2026-11-10T17:00+09:00'],'unknown')
        self.assertNotIn('2026-11-11T04:00+09:00',j['expected']['kma_short'])
        self.assertEqual(len(j['hours']),72)
        self.assertEqual(len(j['latest']),12)
    def test_evening_receipt_and_no_next_morning_issue(self):
        events = [dict(source='kma_midland', issue=issue, status='success',
                       started_kst=at, ended_kst=at) for issue, at in [
                       ('2026112618','2026-11-26T18:34:00+09:00'),
                       ('2026112706','2026-11-27T07:32:00+09:00')]]
        out = self.run_export(events, at='2026-11-27T09:30:00+09:00')
        self.assertEqual(out['matrix']['kma_midland']['2026-11-26T18:00+09:00'], 'success')
        self.assertNotIn('2026-11-27T07:00+09:00', out['expected']['kma_midland'])
        self.assertEqual(next(r for r in out['latest'] if r['source']=='kma_midland')['issue'], '2026112618')

    def test_grace_and_future(self):
        j=self.run_export([self.event('05:25','05:40')],at='2026-11-11T18:00:00+09:00')
        self.assertNotIn('2026-11-11T17:00+09:00',j['matrix']['kma_short'])
        self.assertIn('2026-11-11T23:00+09:00',j['expected']['asos'])
        self.assertNotIn('2026-11-11T23:00+09:00',j['matrix'].get('asos',{}))
    def test_delayed_completion(self):
        j=self.run_export([self.event('05:25','07:10')])
        self.assertEqual(j['matrix']['kma_short']['2026-11-11T05:00+09:00'],'delayed')
    def test_failure_preserved(self):
        j=self.run_export([self.event('05:25','05:30',status='failed'),self.event('05:35','05:40')])
        self.assertEqual(j['matrix']['kma_short']['2026-11-11T05:00+09:00'],'failed')
    def test_no_records_not_outage(self):
        j=self.run_export([])
        self.assertNotIn('missed',[s for row in j['matrix'].values() for s in row.values()])

if __name__=='__main__': unittest.main()

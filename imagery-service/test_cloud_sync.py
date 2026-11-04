import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('cloud', Path(__file__).resolve().parents[1] / 'tools/sync_energy_supabase.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeCloud:
    def __init__(self):
        self.calls = []
        self.report = None

    def request(self, path, method='GET', body=None, headers=None):
        self.calls.append((path, method, body))
        if path.startswith('/rest/v1/energy_reports') and method == 'POST':
            self.report = body['report']
        if path.startswith('/rest/v1/energy_reports') and method == 'GET':
            return [{'report': self.report}]

    def list_folder(self, prefix):
        uid = '11111111-1111-4111-8111-111111111111'
        if not prefix:
            return [{'name': uid}]
        if prefix == uid:
            return [{'name': day} for day in ['20261005', '20261006', '20261104']]
        return [{'id': 'object', 'name': 'a' * 64 + '.png'}]


class SyncTests(unittest.TestCase):
    def test_only_generated_metadata_is_upserted_and_expired_data_removed(self):
        cloud = FakeCloud()
        self.assertEqual(module.sync(cloud, '2026-11-04', {'source': 'published'}, dt.date(2026, 11, 4)), 1)
        writes = [x for x in cloud.calls if x[1] in ['POST', 'PATCH', 'PUT']]
        self.assertEqual(len(writes), 1)
        self.assertNotIn('energy_edits', writes[0][0])
        deletes = [x for x in cloud.calls if x[1] == 'DELETE']
        self.assertEqual(len(deletes), 3)
        self.assertTrue(all('day=lt.2026-10-06' in x[0] for x in deletes[:2]))
        self.assertIn('/20261005/', deletes[2][2]['prefixes'][0])

    def test_invalid_date_prevents_all_writes(self):
        cloud = FakeCloud()
        with self.assertRaises(ValueError):
            module.sync(cloud, '2026-12-01', {}, dt.date(2026, 11, 4))
        self.assertEqual(cloud.calls, [])

    def test_failed_verification_does_not_delete_anything(self):
        cloud = FakeCloud()
        request = cloud.request
        cloud.request = lambda path, method='GET', body=None, headers=None: [] if method == 'GET' else request(path, method, body, headers)
        with self.assertRaises(RuntimeError):
            module.sync(cloud, '2026-11-04', {}, dt.date(2026, 11, 4))
        self.assertFalse(any(x[1] == 'DELETE' for x in cloud.calls))


if __name__ == '__main__':
    unittest.main()

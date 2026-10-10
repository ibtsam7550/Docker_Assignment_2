"""Logic checks. These do not replace an actual Docker experiment on your Mac."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import autoscaler as a
from solver import solve
from httperf_parser import parse


def backend(number, status='healthy'):
    return {'Id': str(number) * 64, 'Name': '/app' + str(number), 'Created': str(number),
            'State': {'Running': True, 'Health': {'Status': status}},
            'NetworkSettings': {'Networks': {a.NETWORK: {'IPAddress': '172.18.0.' + str(number)}}}}


class LabTests(unittest.TestCase):
    def test_all_quadratic_cases(self):
        self.assertEqual(solve(1, -3, 2)[2], [2, 1])
        self.assertEqual(solve(1, 2, 1)[2], [-1])
        self.assertEqual(solve(1, 0, 1)[2], [])
        with self.assertRaises(ValueError):
            solve(0, 2, 1)

    def test_only_healthy_upstreams(self):
        config = a.configuration([backend(1), backend(2, 'unhealthy'), backend(3, 'starting')])
        self.assertIn('172.18.0.1:8000', config)
        self.assertNotIn('172.18.0.2', config)
        self.assertNotIn('172.18.0.3', config)
        self.assertIn('return 503', a.configuration([]))

    def test_metrics_average_and_each_container(self):
        raw = '\n'.join(json.dumps({'Name': 'app' + str(i), 'CPUPerc': str(cpu) + '%',
            'MemPerc': str(mem) + '%', 'MemUsage': '100MiB / 1GiB'})
            for i, cpu, mem in [(1, 80, 20), (2, 40, 30)])
        with patch.object(a, 'docker', return_value=raw), patch.object(a, 'append_csv') as write:
            average = a.metrics([backend(1), backend(2)])
            self.assertEqual(average, 60)
            self.assertEqual(write.call_count, 3)
            self.assertEqual(write.call_args.args[1]['avg_memory'], 25)
            self.assertEqual(write.call_args.args[1]['container_count'], 2)

    def test_incomplete_metrics_do_not_become_zero(self):
        with patch.object(a, 'docker', return_value=''), patch.object(a, 'append_csv') as write:
            with self.assertRaises(RuntimeError):
                a.metrics([backend(1)])
            write.assert_not_called()

    def test_drain_before_stop(self):
        steps = []
        def sync(containers, force=False):
            self.assertEqual([c['Id'] for c in containers], [backend(1)['Id']])
            steps.append('reload_without_victim')
            return {'old-worker'}
        workers = iter([{'old-worker', 'new-worker'}, {'new-worker'}])
        def poll():
            result = next(workers)
            steps.append('old_still_running' if 'old-worker' in result else 'old_finished')
            return result
        with patch.object(a, 'sync_nginx', side_effect=sync), patch.object(a, 'worker_pids', side_effect=poll), \
             patch.object(a, 'docker', side_effect=lambda *args, **kw: steps.append(args[0])), \
             patch.object(a, 'apps', return_value=[backend(1)]), patch.object(a, 'event'), patch.object(a.time, 'sleep'):
            a.scale_in([backend(1), backend(2)], {'drain_timeout_seconds': 10})
        self.assertEqual(steps, ['reload_without_victim', 'old_still_running', 'old_finished', 'stop', 'rm'])

    def test_failed_drain_never_stops_container(self):
        with patch.object(a, 'sync_nginx', return_value={'old-worker'}), patch.object(a, 'event'), \
             patch.object(a.time, 'monotonic', side_effect=[0, 121]), patch.object(a, 'docker') as docker:
            with self.assertRaisesRegex(RuntimeError, 'kept running'):
                a.scale_in([backend(1), backend(2)], {'drain_timeout_seconds': 120})
            docker.assert_not_called()

    def test_no_healthy_survivor_never_reloads_or_stops(self):
        with patch.object(a, 'sync_nginx') as sync, patch.object(a, 'docker') as docker:
            with self.assertRaisesRegex(RuntimeError, 'no healthy'):
                a.scale_in([backend(1, 'unhealthy'), backend(2, 'unhealthy')], {'drain_timeout_seconds': 10})
            sync.assert_not_called()
            docker.assert_not_called()

    def test_invalid_nginx_config_is_restored(self):
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / 'default.conf'
            config.write_text('old config')
            def docker(*args, **kw):
                if args[0] == 'ps':
                    return 'nginx-id'
                raise RuntimeError('syntax check failed')
            with patch.object(a, 'CONF', config), patch.object(a, 'docker', side_effect=docker):
                with self.assertRaisesRegex(RuntimeError, 'syntax check failed'):
                    a.sync_nginx([backend(1)], force=True)
                self.assertEqual(config.read_text(), 'old config')

    def test_httperf_parser_errors_and_missing_data(self):
        fixture = '''Total: connections 100 requests 100 replies 95 test-duration 10.000 s
Request rate: 10.0 req/s
Reply time [ms]: response 25.0 transfer 0.2
Connection time [ms]: min 2.0 avg 26.0 max 60.0
Reply status: 1xx=0 2xx=90 3xx=0 4xx=0 5xx=5
Errors: total 5 client-timo 5 socket-timo 0 connrefused 0 connreset 0
Errors: fd-unavail 0 addrunavail 0 ftab-full 0 other 0
'''
        row = parse(fixture)
        self.assertEqual(row['successful_req_s'], 9)
        self.assertEqual(row['response_ms'], 25)
        self.assertEqual(row['http_5xx'], 5)
        self.assertEqual(row['errors'], 5)
        self.assertIsNone(parse('no summary')['response_ms'])


if __name__ == '__main__':
    unittest.main()

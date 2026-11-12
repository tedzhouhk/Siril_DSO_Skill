"""Portable transport tests. No Siril process or astronomy files are touched."""
import contextlib
from enum import IntEnum
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'siril-deep-sky' / 'scripts'


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


server = module('siril_bridge')
client = module('siril_client')


class STF(IntEnum):
    LINEAR_DISPLAY = 0
    AUTOSTRETCH_DISPLAY = 5


class FakeSiril:
    def __init__(self, directory):
        self.directory = str(directory)
        self.connected = False
        self.calls = []
        self.log_text = ''
        self.mode = STF.LINEAR_DISPLAY
        self.linked = False
        self.shape = (3, 9, 13)
        self.fail_snapshot = False

    def connect(self): self.connected = True
    def disconnect(self): self.connected = False
    def log(self, message): self.log_text += '\n' + message
    def is_image_loaded(self): return True
    def get_siril_wd(self): return self.directory
    def get_image_filename(self):
        if self.fail_snapshot:
            raise RuntimeError('simulated snapshot error')
        return 'unsaved_edit.fit'
    def get_image_shape(self): return self.shape
    def get_siril_stf(self): return self.mode
    def set_siril_stf(self, mode): self.mode = mode
    def set_siril_stf_linked(self, linked): self.linked = linked
    def get_siril_log(self): return self.log_text
    def cmd(self, *args):
        self.calls.append(args)
        if args == ('help', 'fail'):
            self.log('specific diagnostic: simulated failure')
            raise RuntimeError('simulated command failure')
        if args == ('help', 'slow'):
            time.sleep(.12)
        if args == ('help', 'snapshot_error'):
            self.fail_snapshot = True


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='siril_transport_')
        self.base = Path(self.temp.name) / 'target space 星云'
        self.fake = FakeSiril(self.base)
        self.errors = []
        api = SimpleNamespace(SirilInterface=lambda: self.fake, STFType=STF)

        def run():
            try:
                server.serve(self.base, idle_seconds=20, poll_interval=.01, api=api)
            except BaseException as exc:
                self.errors.append(exc)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not (self.base / 'status.json').exists():
            if time.monotonic() > deadline:
                self.fail(f'Bridge did not start: {self.errors}')
            time.sleep(.01)
        self.state = self.read_state()
        self.assertTrue(self.state['connected'])

    def read_state(self):
        return json.loads((self.base / 'status.json').read_text(encoding='utf-8'))

    def request(self, item):
        name = client.submit(self.base, item)
        return client.wait_result(self.base, name, timeout=3, poll_interval=.01)

    def tearDown(self):
        self.fake.fail_snapshot = False
        if self.thread.is_alive():
            self.request({'op': 'stop'})
            self.thread.join(3)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(self.fake.connected)
        self.assertFalse(self.errors)
        self.temp.cleanup()

    def test_live_state_and_display_do_not_modify_pixels(self):
        self.fake.shape = (3, 7, 11)
        status = self.request({'op': 'status'})
        self.assertEqual(status['image_shape'], [3, 7, 11])
        result = self.request({'op': 'display', 'mode': 'autostretch', 'linked': True})
        self.assertTrue(result['ok'])
        self.assertEqual(self.fake.mode, STF.AUTOSTRETCH_DISPLAY)
        self.assertTrue(self.fake.linked)
        self.assertEqual(self.fake.calls, [])

    def test_duplicate_server_lock_preserves_session(self):
        with self.assertRaises(RuntimeError):
            with server.instance_lock(self.base / 'instance.lock'):
                self.fail('Duplicate instance acquired the lock')
        self.assertEqual(self.read_state()['session'], self.state['session'])

    def test_invalid_requests_do_not_reach_siril(self):
        requests = [
            {'session': 'stale', 'op': 'command', 'args': ['stat']},
            {'session': self.state['session'], 'op': 'command', 'args': ['load', 'x\nexit']},
            {'session': self.state['session'], 'op': 'command', 'args': ['exit']},
            {'session': self.state['session'], 'op': 'display', 'mode': 'linear', 'linked': 'yes'},
        ]
        for index, request in enumerate(requests):
            name = f'invalid_{index}.json'
            server.atomic_json(self.base / 'inbox' / name, request)
            result = client.wait_result(self.base, name, timeout=3, poll_interval=.01)
            self.assertFalse(result['ok'])
            self.assertFalse(result['action_completed'])
        self.assertEqual(self.fake.calls, [])

    def test_failed_plan_stops_and_retains_log(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            client.run_plan(self.base, [['help', 'fail'], ['stat']], timeout=3)
        self.assertEqual(self.fake.calls, [('help', 'fail')])
        results = [json.loads(f.read_text(encoding='utf-8')) for f in (self.base / 'outbox').glob('*.json')]
        self.assertTrue(any('specific diagnostic' in r.get('log_tail', '') for r in results))

    def test_timeout_can_wait_for_same_request_without_resubmitting(self):
        name = client.submit(self.base, ['help', 'slow'])
        with self.assertRaises(TimeoutError):
            client.wait_result(self.base, name, timeout=.02, poll_interval=.005)
        self.assertTrue(client.wait_result(self.base, name, timeout=3, poll_interval=.01)['ok'])
        time.sleep(.04)
        self.assertEqual(self.fake.calls.count(('help', 'slow')), 1)

    def test_command_success_with_snapshot_failure_is_not_execution_failure(self):
        result = self.request(['help', 'snapshot_error'])
        self.assertTrue(result['ok'])
        self.assertTrue(result['action_completed'])
        self.assertIn('diagnostic_error', result)
        status = self.request({'op': 'status'})
        self.assertFalse(status['ok'])
        self.assertEqual(self.fake.calls, [('help', 'snapshot_error')])

    def test_stop_disconnects_and_releases_lock(self):
        self.assertTrue(self.request({'op': 'stop'})['ok'])
        self.thread.join(3)
        self.assertFalse(self.read_state()['connected'])
        with server.instance_lock(self.base / 'instance.lock'):
            pass


class ClientStateTests(unittest.TestCase):
    def test_unavailable_or_stale_idle_session_is_not_submitted(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'inbox').mkdir()
            for state in [
                {'connected': False},
                {'connected': True, 'heartbeat': time.time() - 60, 'session': 'old'},
            ]:
                server.atomic_json(base / 'status.json', state)
                with self.assertRaises(RuntimeError):
                    client.submit(base, ['stat'])
            self.assertEqual(list((base / 'inbox').iterdir()), [])

    def test_response_identity_and_wait_path_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'outbox').mkdir()
            server.atomic_json(base / 'outbox' / 'response.json', {'request': 'different.json'})
            with self.assertRaises(ValueError):
                client.wait_result(base, 'response.json', timeout=.1)
            with self.assertRaises(ValueError):
                client.wait_result(base, '../response.json', timeout=.1)


if __name__ == '__main__':
    unittest.main()

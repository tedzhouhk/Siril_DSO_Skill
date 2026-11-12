"""Run with Siril pyscript from a task's process directory; no network listener."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
import traceback
import uuid

ALLOWED = {
    'help', 'requires', 'cd', 'pwd', 'load', 'load_seq', 'close', 'convert', 'link',
    'setext', 'set32bits', 'calibrate', 'calibrate_single', 'stack', 'register',
    'seqapplyreg', 'setref', 'setfindstar', 'seqstat', 'stat', 'findstar', 'clearstar',
    'select', 'unselect', 'setcpu', 'setmem', 'save', 'pyscript', 'platesolve',
    'spcc', 'spcc_list', 'pcc', 'starnet', 'crop', 'rgbcomp', 'savetif', 'savetif32',
    'savejpg', 'savepng', 'subsky', 'setphot', 'icc_remove', 'visu'
}


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


@contextmanager
def instance_lock(path):
    """An OS lock is released on process exit, including a crash."""
    handle = Path(path).open('a+b')
    locked = False
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise RuntimeError('A bridge already owns this directory; reuse its session.') from exc
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def validate_request(request, session):
    if not isinstance(request, dict) or request.get('session') != session:
        raise ValueError('Incorrect or expired bridge session')
    op = request.get('op')
    if op not in {'status', 'command', 'display', 'stop'}:
        raise ValueError('Unsupported operation')
    if op == 'command':
        args = request.get('args')
        if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
            raise ValueError('args must be a nonempty list of strings')
        if args[0] not in ALLOWED or any(any(c in a for c in '\r\n\0') for a in args):
            raise ValueError('Unsupported command or embedded control character')
    if op == 'display':
        if request.get('mode') not in {'linear', 'autostretch'}:
            raise ValueError('Unknown display mode')
        if 'linked' in request and not isinstance(request['linked'], bool):
            raise ValueError('linked must be a boolean')
    return op


def snapshot(siril):
    loaded = siril.is_image_loaded()
    return {
        'cwd': siril.get_siril_wd(), 'image_loaded': loaded,
        'image_filename': siril.get_image_filename() if loaded else None,
        'image_shape': list(siril.get_image_shape()) if loaded else None,
        'display_mode': int(siril.get_siril_stf()) if loaded else None,
    }


def serve(base, idle_seconds=21600, poll_interval=0.5, api=None):
    if api is None:
        import sirilpy as api
    base = Path(base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    with instance_lock(base / 'instance.lock'):
        inbox, outbox = base / 'inbox', base / 'outbox'
        inbox.mkdir(exist_ok=True)
        outbox.mkdir(exist_ok=True)
        state_path = base / 'status.json'
        session = uuid.uuid4().hex
        state = {'version': 3, 'session': session, 'pid': os.getpid(),
                 'started': time.time(), 'connected': False, 'idle_seconds': idle_seconds}
        siril = None
        seen = set()
        last_action = time.monotonic()
        last_beat = 0.0
        try:
            siril = api.SirilInterface()
            siril.connect()
            state.update(snapshot(siril), connected=True, heartbeat=time.time())
            atomic_json(state_path, state)
            siril.log('Codex connected to this Siril window. Waiting for the next processing step.')
            while time.monotonic() - last_action < idle_seconds:
                if time.monotonic() - last_beat > 5:
                    state['heartbeat'] = time.time()
                    atomic_json(state_path, state)
                    last_beat = time.monotonic()
                for path in sorted(inbox.glob('*.json')):
                    if path.name in seen or (outbox / path.name).exists():
                        continue
                    seen.add(path.name)
                    result = {'session': session, 'request': path.name, 'started': time.time(),
                              'ok': False, 'action_completed': False}
                    stop = False
                    valid = False
                    op = None
                    try:
                        request = json.loads(path.read_text(encoding='utf-8'))
                        op = validate_request(request, session)
                        valid = True
                        state.update(busy_request=path.name, heartbeat=time.time())
                        if op == 'command':
                            state['command'] = request['args']
                        atomic_json(state_path, state)
                        if op == 'command':
                            try:
                                siril.log('Codex step: ' + ' '.join(request['args']))
                            except Exception:
                                pass
                            siril.cmd(*request['args'])
                        elif op == 'display':
                            mode = (api.STFType.LINEAR_DISPLAY if request['mode'] == 'linear'
                                    else api.STFType.AUTOSTRETCH_DISPLAY)
                            siril.set_siril_stf(mode)
                            if 'linked' in request:
                                siril.set_siril_stf_linked(request['linked'])
                        elif op == 'stop':
                            stop = True
                        result.update(ok=True, action_completed=True)
                        try:
                            current = snapshot(siril)
                            state.update(current)
                            result.update(current)
                        except Exception as exc:
                            result['diagnostic_error'] = str(exc)
                            if op == 'status':
                                result.update(ok=False, action_completed=False, error=str(exc))
                    except Exception as exc:
                        result.update(error=str(exc), traceback=traceback.format_exc())
                    if op == 'command':
                        try:
                            result['log_tail'] = siril.get_siril_log()[-20000:].rstrip('\0')
                        except Exception as exc:
                            result['log_error'] = str(exc)
                    result['finished'] = time.time()
                    atomic_json(outbox / path.name, result)
                    state.pop('command', None)
                    state.pop('busy_request', None)
                    state['heartbeat'] = time.time()
                    atomic_json(state_path, state)
                    if valid:
                        last_action = time.monotonic()
                    if stop:
                        return
                time.sleep(poll_interval)
            siril.log('Codex bridge idle timeout. Run the bridge script again to reconnect.')
        except Exception as exc:
            state['error'] = str(exc)
            raise
        finally:
            try:
                if siril is not None and siril.connected:
                    siril.disconnect()
            finally:
                state.pop('busy_request', None)
                state.pop('command', None)
                state.update(connected=False, heartbeat=time.time())
                atomic_json(state_path, state)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-dir', type=Path, default=Path(__file__).resolve().parent / 'bridge')
    parser.add_argument('--idle-seconds', type=float, default=21600)
    args = parser.parse_args()
    if args.idle_seconds <= 0:
        parser.error('--idle-seconds must be positive')
    serve(args.bridge_dir, args.idle_seconds)

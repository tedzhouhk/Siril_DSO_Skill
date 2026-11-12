"""Send JSON plans to a running Siril bridge, or wait for a previously submitted request."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid


def submit(base, item):
    base = Path(base)
    state = json.loads((base / 'status.json').read_text(encoding='utf-8'))
    if not state.get('connected'):
        raise RuntimeError('Bridge is not connected')
    if time.time() - state.get('heartbeat', 0) > 30 and not state.get('busy_request'):
        raise RuntimeError('Bridge heartbeat is stale; inspect the Siril session')
    request = {'op': 'command', 'args': item} if isinstance(item, list) else dict(item)
    request['session'] = state['session']
    name = f'{time.time_ns()}_{uuid.uuid4().hex[:12]}.json'
    path = base / 'inbox' / name
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)
    return name


def wait_result(base, name, timeout=3600, poll_interval=0.5):
    if Path(name).name != name or not name.endswith('.json'):
        raise ValueError('--wait-for requires a request filename, not a path')
    response = Path(base) / 'outbox' / name
    start = time.monotonic()
    while not response.exists():
        if time.monotonic() - start >= timeout:
            raise TimeoutError(f'Request may still be running; do not resubmit. Resume with --wait-for {name}')
        time.sleep(poll_interval)
    result = json.loads(response.read_text(encoding='utf-8'))
    if result.get('request') != name:
        raise ValueError('Response ID does not match request')
    return result


def run_plan(base, plan, timeout=3600):
    if not isinstance(plan, list):
        raise ValueError('A plan must be a JSON array')
    results = []
    for item in plan:
        name = submit(base, item)
        print('Submitted: ' + name, flush=True)
        result = wait_result(base, name, timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        results.append(result)
        if not result.get('ok'):
            raise RuntimeError(f'Request {name} failed; later plan items were not submitted')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-dir', type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--plan', type=Path)
    source.add_argument('--wait-for')
    parser.add_argument('--timeout', type=float, default=3600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.plan:
        run_plan(args.bridge_dir, json.loads(args.plan.read_text(encoding='utf-8-sig')), args.timeout)
    else:
        result = wait_result(args.bridge_dir, args.wait_for, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get('ok') else 1)

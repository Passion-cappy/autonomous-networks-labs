"""Independent network probes: no Docker socket, privileged mode or external target."""
import argparse, importlib.util, json, socket, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

def get(url):
    with urlopen(url, timeout=4) as response:
        assert response.status == 200, f'HTTP {response.status}'
        body = response.read().decode()
        return json.loads(body) if response.headers.get_content_type() == 'application/json' else body.strip()

def query(expression):
    value = get('http://prometheus:9090/api/v1/query?' + urlencode({'query': expression}))
    assert value['status'] == 'success'
    return value['data']['result']

def wait(fn, seconds=50):
    deadline = time.monotonic() + seconds
    last = 'No observations'
    while time.monotonic() < deadline:
        try:
            return fn()
        except (OSError, AssertionError, KeyError, ValueError, TypeError) as error:
            last = str(error)
            time.sleep(1)
    raise AssertionError(last or 'Expected observation not received within timeout')

def identity(args):
    def sample():
        value = get(args.url)
        assert value == args.expected, f'{args.url} returned {value!r}'
        return {'url': args.url, 'body': value}
    return wait(sample, 25)

def isolation(args):
    assert args.ips, 'No actual admin IPv4 addresses: isolation cannot be established'
    observations = []
    for address in args.ips.split(','):
        assert address and all(c in '0123456789.' for c in address)
        try:
            with socket.create_connection((address, 8000), timeout=2):
                reachable = True
        except OSError:
            reachable = False
        observations.append({'ip': address, 'tcp_8000_reachable': reachable})
    leaked = [x['ip'] for x in observations if x['tcp_8000_reachable']]
    if args.expected == 'blocked':
        assert not leaked, 'GUEST_LEAK: admin TCP port reachable at ' + ', '.join(leaked)
    else:
        assert leaked, 'Negative control did not make admin reachable'
    return observations

def metrics(args):
    targets = {'http://gateway:8080/health': 1, 'http://backend-a:8000/health': int(args.expected)}
    if args.mode == 'wrong-port':
        targets = {'http://gateway:8080/health': 1, 'http://backend-a:8999/health': 0}
    def sample():
        data = query('probe_success')
        values = {x['metric']['instance']: float(x['value'][1]) for x in data}
        collected = query('up{job="blackbox"}')
        up = {x['metric']['instance']: float(x['value'][1]) for x in collected}
        timestamps = query('timestamp(probe_success)')
        actual_time = {x['metric']['instance']: float(x['value'][1]) for x in timestamps}
        for target, expected in targets.items():
            assert values.get(target) == expected, f'{target}: probe_success={values.get(target)}, expected {expected}'
            assert up.get(target) == 1, f'{target}: exporter up={up.get(target)}, expected 1'
            assert actual_time.get(target, 0) >= args.since, f'{target}: stale sample from an earlier experiment'
        return {'probe_success': values, 'exporter_up': up, 'sample_timestamps': actual_time, 'not_before': args.since}
    return wait(sample, 65)

def notification(args):
    def sample():
        events = get('http://events:8001/events')
        from datetime import datetime
        fresh = []
        for event in events:
            if datetime.fromisoformat(event['at']).timestamp() < args.since:
                continue
            for alert in event['payload']['alerts']:
                labels = alert.get('labels', {})
                started = datetime.fromisoformat(alert['startsAt'].replace('Z', '+00:00')).timestamp()
                if alert['status'] == args.expected and labels.get('alertname') == 'PrimaryBackendUnavailable' and labels.get('instance') == 'http://backend-a:8000/health' and started >= args.since - 3:
                    fresh.append({'received_at': event['at'], 'status': alert['status'], 'startsAt': alert['startsAt'], 'endsAt': alert.get('endsAt'), 'fingerprint': alert.get('fingerprint')})
        assert fresh, 'No fresh ' + args.expected + ' notification for this controlled incident'
        return fresh
    return wait(sample, 80)

def grafana(args):
    def sample():
        health = get('http://grafana:3000/api/health')
        assert health['database'] == 'ok'
        dashboard = get('http://grafana:3000/api/dashboards/uid/netlab')['dashboard']
        expressions = {target.get('expr') for panel in dashboard.get('panels', []) for target in panel.get('targets', [])}
        assert {'probe_success', 'probe_duration_seconds'}.issubset(expressions), expressions
        data = get('http://grafana:3000/api/datasources/proxy/uid/netlab-prometheus/api/v1/query?query=probe_success')['data']['result']
        assert any(x['metric'].get('instance') == 'http://gateway:8080/health' and x['value'][1] == '1' for x in data), data
        return {'version': health.get('version'), 'dashboard_uid': dashboard['uid'], 'expressions': sorted(expressions), 'live_samples': data}
    return wait(sample, 60)

def ai(args):
    spec = importlib.util.spec_from_file_location('diagnose', Path(__file__).with_name('diagnose.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main(args.expected)
    if args.mode == 'ai-off':
        assert result['analysis_status'] == 'unavailable', result
    elif args.expected != 'snapshot':
        assert result['analysis_status'] == 'completed', result
        assert result.get('local_model_digest') and result['executed_actions'] == []
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['identity', 'isolation', 'metrics', 'wrong-port', 'notification', 'grafana', 'ai', 'ai-off'])
    parser.add_argument('--url'); parser.add_argument('--expected', default='1')
    parser.add_argument('--ips'); parser.add_argument('--since', type=float, default=0)
    args = parser.parse_args()
    functions = {'identity': identity, 'isolation': isolation, 'metrics': metrics, 'wrong-port': metrics,
                 'notification': notification, 'grafana': grafana, 'ai': ai, 'ai-off': ai}
    try:
        value = functions[args.mode](args)
        result = {'ok': True, 'observed': value}
    except (Exception, SystemExit) as error:
        result = {'ok': False, 'observed': type(error).__name__ + ': ' + str(error)}
    print('NETLAB_PROBE_RESULT ' + json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1

if __name__ == '__main__':
    raise SystemExit(main())

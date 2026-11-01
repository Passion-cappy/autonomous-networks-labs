"""Docker/Compose checks and bounded experiments; run by check.sh, using only stdlib."""
import argparse
import hashlib
import json
import math
import os
import subprocess
import time
import uuid
import sys
from diagnostics import collect
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree

HERE = Path(__file__).resolve().parent
COMMON = ['CONFIG', 'SAFETY', 'IMAGES', 'TOOLS', 'PERSIST', 'RESTART', 'LOGS']
NETWORK = ['EMP_PUBLIC', 'EMP_ADMIN', 'GUEST_PUBLIC', 'GUEST_DENIED']
FAULT = ['FAILOVER', 'FIRING', 'RESOLVED', 'PRIMARY_RETURN']
AI = ['AI_NORMAL', 'AI_INCIDENT', 'AI_LIMITED', 'AI_CONTRACT', 'AI_OFF', 'ALARM_WITHOUT_AI']

EXPECT = {
    'LOGS': ('Після досліду всі потрібні сервіси працюють; немає несподіваних помилок у журналах', 'Відкрийте diagnostics/diagnostics.json і журнал названого сервісу; виправте причину й повторіть повну перевірку.'),
    'AI_CONTRACT': ('Невалідні AI JSON, чужі E-ID та неповні результати оцінювання відхиляються', 'Використовуйте незмінні supplied tests і правильну структуру відповіді; дивіться AI_INCIDENT та AI_LIMITED.'),
    'CONFIG': ('Compose описує потрібні сервіси та власну побудову toolbox', 'Заповніть Dockerfile/Compose; запустіть tests/compose.sh ЕТАП config.'),
    'SAFETY': ('Toolbox лише у внутрішній control, без capabilities і нових привілеїв, з лімітами RAM/CPU; ресурси лишаються в межах проєкту', 'Перевірте internal:true, networks:[control], cap_drop:[ALL], no-new-privileges:true та додатні mem_limit/cpus. Приберіть privileged, host namespaces, Docker socket і mounts поза проєктом.'),
    'IMAGES': ('Запущені upstream-сервіси використовують перевірені image refs', 'Візьміть refs із .env.example, виконайте pull/up -d; не підміняйте latest невідомим stable.'),
    'TOOLS': ('У toolbox працюють curl, ip, ping і git', 'Перевірте RUN apk add у Dockerfile та перебудуйте образ.'),
    'PERSIST': ('Власний контрольний файл переживає перестворення toolbox', 'Перевірте bind mount ./ → /workspace; файли мають бути у каталозі проєкту.'),
    'RESTART': ('Після stop/start toolbox запускається й виконує команду', 'Подивіться compose ps і logs toolbox; перевірте CMD та робочий каталог.'),
    'EMP_PUBLIC': ('Працівник отримує backend-a через gateway:8080', 'Перевірте work-мережу, gateway і HAProxy backend.'),
    'EMP_ADMIN': ('Працівник отримує admin через admin:8000', 'Перевірте спільну work-мережу та site/admin/identity.'),
    'GUEST_PUBLIC': ('Гість отримує backend-a через gateway:8080', 'Підключіть gateway до guest; перевірте HTTP frontend.'),
    'GUEST_DENIED': ('За доступного admin працівнику TCP-доступ гостя до всіх admin IP заблокований', 'Перевірте всі інтерфейси admin: DNS-помилка сама по собі не доводить ізоляцію.'),
    'LEAK_CONTROL': ('Доданий guest-інтерфейс виявляється; після disconnect ізоляція повертається', 'Спочатку відновіть правильну топологію; тест змінює лише власноруч доданий інтерфейс.'),
    'METRICS': ('Дві штатні цілі: probe_success=1, exporter up=1, зразки свіжі', 'Перевірте targets, relabel_configs, мережі Blackbox і час останнього scrape.'),
    'WRONG_PORT': ('Порт 8999: свіжа probe_success=0 при exporter up=1', 'Перевірте exporter окремо від HTTP-цілі; старий зразок не зараховується.'),
    'METRICS_RESTORED': ('Після повернення конфігурації штатні цілі знову мають свіжі успішні проби', 'Перевірте config/prometheus.yml і restart prometheus.'),
    'FAILOVER': ('Після stop backend-a gateway відповідає через backend-b', 'Перевірте server reserve ... backup, health check та сервіс backend-b.'),
    'FIRING': ('Нове firing сповіщення саме цього інциденту надійшло до events', 'Перевірте alert rule, evaluation, Alertmanager route, URL webhook і for.'),
    'RESOLVED': ('Після start backend-a надійшло нове resolved цього ж інциденту', 'Перевірте send_resolved:true та відновлення primary.'),
    'PRIMARY_RETURN': ('Gateway знову відповідає backend-a; прямий primary probe успішний', 'Дочекайтеся health checks; перевірте, що primary не лишився down.'),
    'GRAFANA': ('Панель має обидві PromQL-серії й отримує живі дані через datasource', 'Перевірте provisioning, datasource URL/UID і стандартний образ Grafana.'),
    'AI_NORMAL': ('Реальний локальний inference завершується; JSON має допустимі E-ID', 'Перевірте MODEL, ollama pull, пам’ять і config/ai-prompt.txt.'),
    'AI_INCIDENT': ('Локальна модель аналізує новий знімок контрольованої відмови', 'Звірте incident_id зі знімком; правильність гіпотез оцініть за доказами.'),
    'AI_LIMITED': ('Є реальна відповідь на позначений знімок без вимірювань', 'Форма JSON не доводить істинності; встановлену без доказів причину спростуйте у протоколі.'),
    'AI_OFF': ('При зупиненій Ollama клієнт фіксує unavailable', 'Це очікуваний негативний дослід, а не заміна обов’язкового inference.'),
    'ALARM_WITHOUT_AI': ('При зупиненій Ollama резерв, нові firing/resolved і повернення primary працюють', 'Приберіть залежність класичного alerting від моделі.'),
}

class Blocked(Exception):
    pass

class CheckFailed(Exception):
    pass

def required(stage):
    n = int(stage[-2:])
    checks = COMMON.copy()
    if n >= 4: checks += NETWORK
    if n == 4: checks += ['LEAK_CONTROL']
    if n >= 5: checks += ['METRICS']
    if n == 5: checks += ['WRONG_PORT', 'METRICS_RESTORED']
    if n >= 6: checks += FAULT
    if n == 7: checks += ['GRAFANA'] + AI
    return checks

def summarize(stage, records, policy, partial=False):
    """Never treat missing/duplicate observations or an oral assessment as a numeric pass."""
    ids = [row['id'] for row in records]
    assert len(ids) == len(set(ids)), 'Duplicate check IDs'
    by_id = {row['id']: row for row in records}
    counts = dict(Counter(row['status'] for row in records))
    criteria = []
    confirmed = 0
    for criterion in policy['criteria']:
        dependencies = criterion.get('checks', [])
        statuses = [by_id.get(key, {}).get('status', 'blocked') for key in dependencies]
        passed = bool(dependencies) and all(value == 'passed' for value in statuses)
        points = criterion['points'] if passed and policy['mode'] == 'automatic' else 0
        confirmed += points
        criteria.append({**criterion, 'confirmed_points': points, 'status': 'passed' if passed else 'not-confirmed'})
    incomplete = any(counts.get(k, 0) for k in ('blocked', 'error', 'skipped')) or not set(required(stage)).issubset(by_id)
    failed = counts.get('failed', 0) > 0
    status = 'failed' if failed else 'partial' if incomplete else 'passed'
    assessed = {key for criterion in policy['criteria'] for key in criterion.get('checks', [])}
    prerequisites = sorted(set(required(stage)) - assessed)
    prerequisite_failures = [key for key in prerequisites if by_id.get(key, {}).get('status') != 'passed']
    score = confirmed if policy['mode'] == 'automatic' and not incomplete and not prerequisite_failures else None
    return {'stage': stage, 'status': status, 'counts': counts, 'total_checks': len(records),
            'completed_checks': counts.get('passed', 0) + counts.get('failed', 0),
            'confirmed_points': confirmed, 'max_points': policy['max_points'],
            'machine_score': score, 'assessment_mode': policy['mode'],
            'final_grade_status': 'oral-defence-pending' if policy['mode'] == 'oral' else 'technical-result',
            'criteria': criteria, 'prerequisite_checks': prerequisites, 'prerequisite_failures': prerequisite_failures,
            'explicit_partial_scope': partial}

class Runner:
    def __init__(self, args):
        self.args = args
        self.project = Path(args.project).resolve()
        self.stage = args.stage
        self.n = int(self.stage[-2:])
        self.run_id = uuid.uuid4().hex
        self.output = Path('/output') / self.run_id
        self.output.mkdir()
        self.daemon_output = Path(args.output_source) / self.run_id
        self.records = {}
        self.config = None
        self.image = os.environ['NETLAB_PROBE_IMAGE']
        self.initial = time.time()
        self.windows = []
        self.ci_partial = os.getenv('NETLAB_CI_WITHOUT_MODEL') == '1' and self.n == 7

    def clean(self, value):
        return str(value).replace(str(self.project), '.').replace(str(HERE), 'tests')[:2500]

    def command(self, args, timeout=100, allowed=(0,)):
        result = subprocess.run(args, cwd=self.project, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        if result.returncode not in allowed:
            raise CheckFailed(self.clean(result.stdout + result.stderr))
        return result

    def dc(self, *args, **kwargs):
        return self.command(['sh', str(HERE / 'compose.sh'), self.stage, *args], **kwargs)

    def inspect(self, identifier):
        return json.loads(self.command(['docker', 'inspect', identifier]).stdout)[0]

    def role(self, name):
        identifier = self.dc('ps', '-aq', name).stdout.strip()
        if not identifier:
            raise Blocked(f'Контейнер {name} не створений: виконайте up відповідного етапу')
        assert self.inspect(identifier)['State']['Running'], f'Контейнер {name} не запущений'
        return identifier

    def probe(self, role, mode, *args, timeout=100, expected_ok=True):
        identifier = self.role(role)
        name = 'netlab-probe-' + uuid.uuid4().hex[:12]
        argv = ['docker', 'run', '--rm', '--name', name, '--label', 'netlab.check=' + self.run_id,
                '--label', 'com.docker.compose.project=' + self.config['name'], '--label', 'com.docker.compose.service=check-probe',
                '--network', 'container:' + identifier, '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                '--memory', '128m', '--pids-limit', '64', '--read-only',
                '--mount', f'type=bind,source={HERE},target=/checks,readonly',
                '--mount', f'type=bind,source={self.project},target=/workspace,readonly',
                '--mount', f'type=bind,source={self.daemon_output},target=/evidence',
                '-w', '/workspace', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'NETLAB_EVIDENCE_DIR=/evidence',
                '-e', 'NETLAB_AI_READINESS_TIMEOUT=' + ('4' if mode == 'ai-off' else '30'),
                '-e', 'MODEL=' + self.config['services']['toolbox'].get('environment', {}).get('MODEL', 'qwen3:0.6b'),
                self.image, 'python', '/checks/probe.py', mode, *map(str, args)]
        try:
            result = self.command(argv, timeout=timeout, allowed=(0, 1))
            rows = [x[len('NETLAB_PROBE_RESULT '):] for x in result.stdout.splitlines() if x.startswith('NETLAB_PROBE_RESULT ')]
            if not rows:
                raise RuntimeError('Проба не повернула структурованого результату: ' + self.clean(result.stderr))
            value = json.loads(rows[-1])
            if expected_ok:
                assert value['ok'], value['observed']
            return value
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)

    def check(self, key, fn, dependencies=()):
        started = time.monotonic()
        expected, hint = EXPECT[key]
        try:
            missing = [x for x in dependencies if self.records.get(x, {}).get('status') != 'passed']
            if missing: raise Blocked('Спочатку виправте: ' + ', '.join(missing))
            observed = fn()
            status = 'passed'
        except Blocked as error:
            status, observed = 'blocked', str(error)
        except (AssertionError, CheckFailed) as error:
            status, observed = 'failed', self.clean(error)
        except Exception as error:
            status, observed = 'error', type(error).__name__ + ': ' + self.clean(error)
        row = {'id': key, 'status': status, 'expected': expected, 'observed': observed,
               'hint': hint, 'seconds': round(time.monotonic() - started, 3)}
        self.records[key] = row
        print(f'[{status.upper()}] {key}: {expected}', flush=True)
        print('  Факт: ' + self.clean(json.dumps(observed, ensure_ascii=False))[:650], flush=True)
        if status != 'passed': print('  Дія: ' + hint, flush=True)
        (self.output / 'progress.json').write_text(json.dumps(list(self.records.values()), ensure_ascii=False, indent=2), encoding='utf-8')
        return status == 'passed'

    def config_check(self):
        self.config = json.loads(self.dc('--profile', 'monitoring', '--profile', 'ai', 'config', '--format', 'json').stdout)
        roles = {'toolbox'}
        if self.n >= 4: roles.update(('employee', 'guest', 'admin', 'backend-a', 'gateway'))
        if self.n >= 5: roles.update(('prometheus', 'blackbox'))
        if self.n >= 6: roles.update(('backend-b', 'events', 'alertmanager'))
        if self.n >= 7: roles.update(('grafana', 'ollama'))
        assert roles.issubset(self.config['services']), 'Не вистачає: ' + str(roles - set(self.config['services']))
        build = self.config['services']['toolbox'].get('build')
        assert build and build['args']['BASE_IMAGE'] == self.image, 'Власний toolbox має будуватися з перевіреної BASE_IMAGE'
        return {'services': sorted(roles), 'compose_project': self.config['name']}

    def safety(self):
        def inside(value):
            try:
                Path(value).resolve().relative_to(self.project)
            except ValueError:
                raise AssertionError('Bind/build path виходить за межі навчального проєкту') from None
        assert all(not network.get('external') for network in self.config.get('networks', {}).values()), 'Зовнішня Docker-мережа не є частиною стенда'
        assert all(not volume.get('external') for volume in self.config.get('volumes', {}).values()), 'Зовнішній volume не є частиною стенда'
        control = self.config.get('networks', {}).get('control', {})
        toolbox = self.config['services']['toolbox']
        assert control.get('internal') is True, 'Мережа control має містити internal: true'
        assert set(toolbox.get('networks', {})) == {'control'}, 'Toolbox має бути підключений лише до control'
        assert 'ALL' in toolbox.get('cap_drop', []), 'Toolbox потребує cap_drop: [ALL]'
        options = {str(value).replace('=', ':') for value in toolbox.get('security_opt', [])}
        assert options & {'no-new-privileges', 'no-new-privileges:true'}, 'Toolbox потребує security_opt: [no-new-privileges:true]'
        for field in ('mem_limit', 'cpus'):
            try:
                value = float(toolbox.get(field, 0))
            except (TypeError, ValueError):
                raise AssertionError('Toolbox потребує додатного числового обмеження ' + field) from None
            assert math.isfinite(value) and value > 0, 'Toolbox потребує додатного обмеження ' + field
        if self.n == 7:
            model = self.config['services']['ollama']
            assert model.get('environment', {}).get('OLLAMA_NO_CLOUD') == '1' and not model.get('ports'), 'LLM має лишатися локальною, з внутрішнім API'
        for name, service in self.config['services'].items():
            assert not service.get('privileged') and not service.get('cap_add') and not service.get('devices'), name
            assert not service.get('network_mode') and service.get('pid') != 'host' and service.get('ipc') != 'host', name
            for port in service.get('ports', []): assert port.get('host_ip') == '127.0.0.1', name + ' публікує порт не на loopback'
            for mount in service.get('volumes', []):
                assert 'docker.sock' not in str(mount), name
                if mount['type'] == 'bind': inside(mount['source'])
            if service.get('build'):
                inside(service['build']['context'])
                assert not service['build'].get('ssh') and not service['build'].get('secrets'), name
        return 'Межі проєкту й обмеження namespace/mount перевірені'

    def image_check(self):
        lock = json.loads((HERE / 'images.lock.json').read_text(encoding='utf-8'))['images']
        mapping = {'gateway': 'HAPROXY_IMAGE', 'prometheus': 'PROMETHEUS_IMAGE', 'blackbox': 'BLACKBOX_IMAGE',
                   'alertmanager': 'ALERTMANAGER_IMAGE', 'grafana': 'GRAFANA_IMAGE', 'ollama': 'OLLAMA_IMAGE'}
        actual = {}
        for key in ('BASE_IMAGE','CI_IMAGE'):
            reference=lock[key]['reference']
            if key=='BASE_IMAGE':assert reference==self.image,'BASE_IMAGE differs from the reviewed lock'
            image=json.loads(self.command(['docker','image','inspect',reference]).stdout)[0]
            assert any(x.endswith('@'+lock[key]['digest']) for x in image.get('RepoDigests',[])), key+': upstream digest differs from the reviewed lock'
        for role, key in mapping.items():
            if role not in self.config['services']: continue
            assert self.config['services'][role]['image'] == lock[key]['reference'], role + ': image ref відрізняється від перевіреного'
            if self.ci_partial and role == 'ollama': continue
            info = self.inspect(self.role(role))
            assert info['Config']['Image'] == lock[key]['reference'], role + ': контейнер створений зі старого ref; виконайте up -d'
            image=self.inspect(info['Image'])
            assert any(x.endswith('@'+lock[key]['digest']) for x in image.get('RepoDigests',[])),role+': image digest differs from the reviewed lock'
            actual[role] = {'reference': info['Config']['Image'], 'runtime_image_id': info['Image']}
        return actual or {'base': self.image}

    def logs(self):
        active={key:value for key,value in self.config['services'].items() if key!='ollama' or not self.ci_partial}
        data=collect({**self.config,'services':active},self.command,self.output/'diagnostics',self.initial,self.windows)
        assert not data['unexpected'],json.dumps(data['unexpected'][:8],ensure_ascii=False)
        return {'services':len(data['services']),'unexpected_errors':0,'expected_fault_messages':len(data['expected']),'errors_related_to_failed_checks':len(data['explained_failure']),'details':'diagnostics/diagnostics.json'}

    def tools(self):
        result = {}
        for tool, arguments in [('curl', ['--version']), ('ip', ['-V']), ('ping', ['-V']), ('git', ['--version'])]:
            result[tool] = self.dc('exec', '-T', 'toolbox', tool, *arguments).stdout.splitlines()[0]
        return result

    def persistence(self):
        marker = 'netlab-' + uuid.uuid4().hex
        folder = self.project / 'results'; folder.mkdir(exist_ok=True)
        source = folder / 'persistence.txt'
        source.write_text(marker, encoding='utf-8')
        before = self.role('toolbox')
        self.dc('up', '-d', '--force-recreate', '--no-deps', 'toolbox')
        after = self.role('toolbox')
        assert before != after, 'Контейнер не був перестворений'
        value = self.dc('exec', '-T', 'toolbox', 'cat', '/workspace/results/persistence.txt').stdout.strip()
        assert value == marker and source.read_text(encoding='utf-8') == marker
        return {'new_container': True, 'marker': marker, 'visible_in_container_and_host': True}

    def restart(self):
        self.dc('stop', '-t', '1', 'toolbox')
        self.dc('start', 'toolbox')
        return self.dc('exec', '-T', 'toolbox', 'git', '--version').stdout.strip()

    def admin_ips(self):
        networks = self.inspect(self.role('admin'))['NetworkSettings']['Networks']
        return ','.join(sorted({x['IPAddress'] for x in networks.values() if x.get('IPAddress')}))

    def leak(self):
        admin = self.role('admin')
        guest_networks = self.inspect(self.role('guest'))['NetworkSettings']['Networks']
        assert len(guest_networks) == 1
        network = next(iter(guest_networks))
        assert network not in self.inspect(admin)['NetworkSettings']['Networks'], 'Admin уже має зайвий guest-інтерфейс'
        self.command(['docker', 'network', 'connect', network, admin])
        try:
            value = self.probe('guest', 'isolation', '--ips', self.admin_ips(), '--expected', 'blocked', expected_ok=False)
            assert not value['ok'] and 'GUEST_LEAK' in str(value['observed']), value
            (self.project / 'results/negative-guest.log').write_text(str(value['observed']) + '\n', encoding='utf-8')
        finally:
            self.command(['docker', 'network', 'disconnect', network, admin])
        repaired = self.probe('guest', 'isolation', '--ips', self.admin_ips(), '--expected', 'blocked')
        return {'fault_detected': value['observed'], 'repaired': repaired['observed']}

    def wrong_port(self):
        path = self.project / 'config/prometheus.yml'
        original = path.read_bytes()
        assert original.count(b'backend-a:8000/health') == 1, 'Очікується одна штатна target backend-a:8000/health'
        since = time.time()
        try:
            path.write_bytes(original.replace(b'backend-a:8000/health', b'backend-a:8999/health'))
            self.dc('restart', '-t', '1', 'prometheus')
            self.check('WRONG_PORT', lambda: self.probe('toolbox', 'wrong-port', '--since', since)['observed'])
        finally:
            path.write_bytes(original)
            self.dc('restart', '-t', '1', 'prometheus')
        restored = time.time()
        self.check('METRICS_RESTORED', lambda: self.probe('toolbox', 'metrics', '--since', restored)['observed'])
        self.windows.append({'kind':'wrong-port','start':since,'end':time.time()})

    def incident(self, record=True, snapshot=False):
        since = time.time()
        self.role('backend-a')
        self.dc('stop', '-t', '1', 'backend-a')
        observations = {}
        def step(key, fn):
            if record:
                self.check(key, fn)
                observations[key] = self.records[key]
            else:
                observations[key] = fn()
        try:
            step('FAILOVER', lambda: self.probe('employee', 'identity', '--url', 'http://gateway:8080/identity', '--expected', 'backend-b')['observed'])
            step('FIRING', lambda: self.probe('toolbox', 'notification', '--since', since, '--expected', 'firing')['observed'])
            logs = self.dc('logs', '--no-color', '--timestamps', '--tail', '8', 'backend-a').stdout
            (self.output / 'backend-a.log').write_text(logs, encoding='utf-8')
            if snapshot:
                self.probe('toolbox', 'ai', '--expected', 'snapshot', timeout=160)
        finally:
            self.dc('start', 'backend-a')
        step('RESOLVED', lambda: self.probe('toolbox', 'notification', '--since', since, '--expected', 'resolved')['observed'])
        step('PRIMARY_RETURN', lambda: self.probe('employee', 'identity', '--url', 'http://gateway:8080/identity', '--expected', 'backend-a')['observed'])
        self.probe('toolbox', 'metrics', '--since', since)
        self.windows.append({'kind':'primary-off','start':since,'end':time.time(),'failover_status':self.records['FAILOVER']['status'] if record else 'passed'})
        complete = not record or all(row['status']=='passed' for row in observations.values())
        print('CLASSICAL_INCIDENT_OK; fresh event, backup and primary recovery observed' if complete else 'CLASSICAL_INCIDENT_FAILED; inspect the failed checks in assessment.json', flush=True)
        return observations

    def ai_off(self):
        self.role('ollama')
        self.dc('stop', '-t', '1', 'ollama')
        try:
            self.check('AI_OFF', lambda: self.probe('toolbox', 'ai-off', '--expected', 'normal', timeout=20)['observed'])
            self.check('ALARM_WITHOUT_AI', lambda: self.incident(record=False))
        finally:
            self.dc('--profile', 'ai', 'start', 'ollama')

    def execute(self):
        valid = self.check('CONFIG', self.config_check)
        safe = valid and self.check('SAFETY', self.safety)
        if safe:
            self.check('IMAGES', self.image_check)
            self.check('TOOLS', self.tools)
            self.check('PERSIST', self.persistence)
            self.check('RESTART', self.restart)
            if self.n >= 4:
                for key, role, url, expected in [('EMP_PUBLIC', 'employee', 'http://gateway:8080/identity', 'backend-a'),
                        ('EMP_ADMIN', 'employee', 'http://admin:8000/identity', 'admin'),
                        ('GUEST_PUBLIC', 'guest', 'http://gateway:8080/identity', 'backend-a')]:
                    self.check(key, lambda role=role, url=url, expected=expected: self.probe(role, 'identity', '--url', url, '--expected', expected)['observed'])
                self.check('GUEST_DENIED', lambda: self.probe('guest', 'isolation', '--ips', self.admin_ips(), '--expected', 'blocked')['observed'], ['EMP_ADMIN'])
            if self.n == 4 and not self.args.quick:
                self.check('LEAK_CONTROL', self.leak, ['GUEST_DENIED', 'EMP_ADMIN'])
            if self.n >= 5:
                self.check('METRICS', lambda: self.probe('toolbox', 'metrics', '--since', self.initial - 10)['observed'])
            if self.n == 5 and not self.args.quick and self.records['METRICS']['status'] == 'passed':
                self.wrong_port()
            if self.n == 7:
                self.check('GRAFANA', lambda: self.probe('toolbox', 'grafana')['observed'])
                if not self.ci_partial:
                    self.check('AI_CONTRACT',lambda:self.command([sys.executable,str(HERE/'contract.py')]).stdout.strip())
                    self.check('AI_NORMAL', lambda: self.probe('toolbox', 'ai', '--expected', 'normal', timeout=220)['observed'])
            if self.n >= 6 and not self.args.quick and self.records['METRICS']['status'] == 'passed':
                self.incident(snapshot=self.n == 7 and not self.ci_partial)
                if self.n == 7 and not self.ci_partial:
                    self.check('AI_INCIDENT', lambda: self.probe('toolbox', 'ai', '--expected', 'incident', timeout=220)['observed'])
                    self.check('AI_LIMITED', lambda: self.probe('toolbox', 'ai', '--expected', 'limited', timeout=220)['observed'])
                    self.ai_off()

    def report(self):
        intentional = set()
        if self.args.quick: intentional.update(['LEAK_CONTROL', 'WRONG_PORT', 'METRICS_RESTORED', *FAULT, 'AI_INCIDENT', 'AI_LIMITED', 'AI_OFF', 'ALARM_WITHOUT_AI'])
        if self.ci_partial: intentional.update(AI)
        for key in required(self.stage):
            if key not in self.records:
                self.records[key] = {'id': key, 'status': 'skipped' if key in intentional else 'blocked',
                    'expected': EXPECT[key][0], 'observed': 'Явно обмежений quick/CI scope' if key in intentional else 'Передумови експерименту не виконані',
                    'hint': EXPECT[key][1], 'seconds': 0}
        policy = json.loads((HERE / 'assessment-policy.json').read_text(encoding='utf-8'))['stages'][self.stage]
        records = [self.records[key] for key in required(self.stage)] + [row for key, row in self.records.items() if key not in required(self.stage)]
        summary = summarize(self.stage, records, policy, bool(intentional))
        value = {'schema': 1, 'run_id': self.run_id, 'started_at': datetime.fromtimestamp(self.initial, timezone.utc).isoformat(),
                 'finished_at': datetime.now(timezone.utc).isoformat(), 'scope': 'local-self-check' if not os.getenv('NETLAB_TRUSTED_GRADER') else 'instructor-controlled-check',
                 **summary, 'checks': records,
                 'checks_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.is_file()},
                 'limitations': ['Not proof of authorship', 'Cloud CI is not proof of a run on a student laptop']}
        (self.output / 'assessment.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        suite = Element('testsuite', name=self.stage)
        for row in records:
            test = SubElement(suite, 'testcase', name=row['id'], classname=self.stage, time=str(row['seconds']))
            if row['status'] in ('failed', 'error'): SubElement(test, 'failure' if row['status'] == 'failed' else 'error', message=row['expected']).text = self.clean(row['observed'])
            elif row['status'] in ('skipped', 'blocked'): SubElement(test, 'skipped', message=self.clean(row['observed']))
        ElementTree(suite).write(self.output / 'junit.xml', encoding='utf-8', xml_declaration=True)
        counts = summary['counts']
        line = f"Результат: {counts.get('passed', 0)}/{len(records)} успішних; помилок {counts.get('failed', 0)}, блокованих {counts.get('blocked', 0)}, пропущених {counts.get('skipped', 0)}, збоїв перевірки {counts.get('error', 0)}."
        grade = f"Оцінка: {summary['machine_score'] if summary['machine_score'] is not None else 'не визначена'} / {summary['max_points']}. Підтверджено {summary['confirmed_points']} балів."
        if summary['machine_score'] is None:grade+=' Потрібна повна перевірка та справні передумови попередніх етапів.'
        md = '---\nid: netlab-check-' + self.run_id + '\ntype: runtime-report\ndiscipline: proektuvannia-avtonomykh-merezh\nstatus: draft\nversion: 1\nupdated: ' + datetime.now(timezone.utc).date().isoformat() + '\nsources: []\n---\n\n# ' + self.stage + '\n\n' + grade + '\n\n' + line + '\n\n| ID | Статус | Очікується |\n|---|---|---|\n'
        md += ''.join('| ' + x['id'] + ' | ' + x['status'] + ' | ' + x['expected'] + ' |\n' for x in records)
        md += '\n| Критерій | Підтверджено | Максимум |\n|---|---:|---:|\n'
        md += ''.join('| ' + x['id'] + ' | ' + str(x['confirmed_points']) + ' | ' + str(x['points']) + ' |\n' for x in summary['criteria'])
        for row in records:
            md += '\n## ' + row['id'] + ': ' + row['status'] + '\n\nОчікується: ' + row['expected'] + '\n\nФакт:\n\n```json\n' + json.dumps(row['observed'], ensure_ascii=False, indent=2) + '\n```\n\nНаступна перевірка: ' + row['hint'] + '\n'
        md += '\nУсі ПР оцінюються автоматично. Це результат перевірки поведінки, а не висновок про авторство. Локальна самоперевірка не є незалежною викладацькою квитанцією.\n'
        (self.output / 'report.md').write_text(md, encoding='utf-8')
        pointer = Path('/output', 'latest-' + self.stage + '.json')
        pointer.write_text(json.dumps({'run_id': self.run_id, 'report': self.run_id + '/assessment.json'}, indent=2), encoding='utf-8')
        owner = Path('/output').stat()
        if owner.st_uid != os.getuid():
            for item in [self.output, *self.output.rglob('*'), pointer]:
                os.chown(item, owner.st_uid, owner.st_gid)
        print('\n' + line + '\n' + grade + '\nАртефакти: results/checks/' + self.run_id + '/{assessment.json,report.md,junit.xml}', flush=True)
        if summary['status'] == 'failed' or counts.get('error') or counts.get('blocked'): return 1
        if summary['status'] == 'partial' and not intentional: return 1
        print(('MACHINE_STAGE_PARTIAL ' if summary['status'] == 'partial' else 'MACHINE_STAGE_OK ') + self.stage + '; automatic rubric, maximum '+str(summary['max_points']), flush=True)
        return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=[f'pr{n:02}' for n in range(3, 8)])
    parser.add_argument('--project', required=True); parser.add_argument('--output-source', required=True)
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    runner = Runner(args)
    try:
        runner.execute()
    except Exception as error:
        runner.records['HARNESS'] = {'id': 'HARNESS', 'status': 'error', 'expected': 'Тестовий сценарій завершено без внутрішнього збою', 'observed': type(error).__name__ + ': ' + runner.clean(error), 'hint': 'Перевірте logs і повторіть запуск; збережіть assessment.json для викладача.', 'seconds': 0}
    finally:
        if runner.records.get('SAFETY',{}).get('status')=='passed':runner.check('LOGS',runner.logs)
    return runner.report()

if __name__ == '__main__':
    raise SystemExit(main())

"""Validate supplied tests/metadata. --empty is only for the instructor's export."""
import ast,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT/'tests').glob('*.py'):ast.parse(p.read_text(encoding='utf-8'),filename=p.name)
lock=json.loads((ROOT/'tests/images.lock.json').read_text(encoding='utf-8'))
for value in lock['images'].values():
    assert '@' not in value['reference'] and len(value['digest'])==71
    assert {'amd64','arm64'}.issubset(value['platforms'])
if '--empty' in sys.argv:
    for name in ('results','reports','.git','models'):
        assert not (ROOT/name).exists(),name+' is runtime/private data, not part of the empty template'
    expected=['Dockerfile','compose.yaml','compose.network.yaml','compose.monitoring.yaml','compose.resilience.yaml','compose.ai.yaml',
      'config/haproxy.cfg','config/prometheus.yml','config/blackbox.yml','config/alerts.yml','config/alertmanager.yml',
      'config/grafana-datasource.yml','config/grafana-provider.yml','config/grafana-dashboard.json','config/ai-prompt.txt',
      'site/admin/health','site/admin/identity','site/backend-a/health','site/backend-a/identity','site/backend-b/health','site/backend-b/identity']
    for name in expected:assert (ROOT/name).read_text(encoding='utf-8').startswith('# TODO:'),name+' leaks a completed configuration'
    for p in ROOT.rglob('*'):
        assert p.name not in ('teacher-key.md','replay.py','runtime-evidence.json') and p.suffix not in ('.docx','.gguf'),p
print('TEMPLATE_METADATA_OK; no student lab completion is implied')

from run import required
import re
bootstrap=(ROOT/'tests/check.sh').read_text(encoding='utf-8')
for n in range(3,8):
    stage=f'pr{n:02}'
    assert f'{stage}) count={len(required(stage))}' in bootstrap, 'Bootstrap count drift: '+stage
policy=json.loads((ROOT/'tests/assessment-policy.json').read_text(encoding='utf-8'))
assert all(v['mode']=='automatic' and not v['oral_defense_required'] and v['max_points']==(12 if k=='pr07' else 10) for k,v in policy['stages'].items())

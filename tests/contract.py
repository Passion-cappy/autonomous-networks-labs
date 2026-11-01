"""Negative controls for the supplied answer validator, not a claim of live inference."""
from diagnose import validate
evidence={'evidence':[{'id':'E1'}]}
valid={'assessment':'insufficient_evidence','summary':'No cause established','probable_causes':[],'evidence_ids':['E1'],'recommended_checks':[]}
assert validate(valid,evidence)==valid
for bad in ({**valid,'execute':'change routes'},{**valid,'evidence_ids':['made-up']},{**valid,'assessment':'certain'},{**valid,'probable_causes':'not a list'}):
    try:validate(bad,evidence)
    except ValueError:pass
    else:raise AssertionError('Invalid output accepted')
print('FOUR_NEGATIVE_CONTRACT_CONTROLS_OK; inference not implied')

import json
from pathlib import Path
from run import COMMON, required, summarize
policies=json.loads(Path(__file__).with_name('assessment-policy.json').read_text(encoding='utf-8'))['stages']
for stage in policies:
    rows=[{'id':key,'status':'passed'} for key in required(stage)]
    value=summarize(stage,rows,policies[stage])
    assert value['status']=='passed'
    assert value['machine_score']==policies[stage]['max_points']
    missing=summarize(stage,rows[:-1],policies[stage])
    assert missing['machine_score'] is None and missing['status']=='partial'
    for status in ('blocked','skipped','error'):
        changed=[{**x,'status':status} if x['id']==rows[-1]['id'] else x for x in rows]
        assert summarize(stage,changed,policies[stage])['machine_score'] is None
    try:summarize(stage,rows+rows[:1],policies[stage])
    except AssertionError:pass
    else:raise AssertionError('Duplicate check ID accepted')
rows=[{'id':key,'status':'failed' if key=='FAILOVER' else 'passed'} for key in required('pr06')]
assert summarize('pr06',rows,policies['pr06'])['machine_score']==7
changed=[{'id':x,'status':'failed' if x=='TOOLS' else 'passed'} for x in required('pr03')]
assert summarize('pr03',changed,policies['pr03'])['machine_score']==7
for key in COMMON:
    changed=[{'id':x,'status':'failed' if x==key else 'passed'} for x in required('pr04')]
    assert summarize('pr04',changed,policies['pr04'])['machine_score'] is None
print('ASSESSMENT_NEGATIVE_CONTROLS_OK; missing, blocked, skipped, error, duplicate, partial score, automatic policy')

from diagnostics import classify
assert classify('2026-10-31T00:00:01Z [ALERT] config parsing failed','gateway',[])['classification']=='unexpected'
window=[{'kind':'primary-off','start':1793404800,'end':1793404810}]
assert classify('2026-10-31T00:00:01Z [ALERT] backend application has no server available','gateway',window)['classification']=='expected'
assert classify('2026-10-31T00:00:20Z [ALERT] backend application has no server available','gateway',window)['classification']=='unexpected'
assert classify('2026-10-31T00:00:01Z Traceback','backend-a',window)['classification']=='unexpected'
print('LOG_WINDOW_NEGATIVE_CONTROLS_OK')
wrong=[{'kind':'wrong-port','start':1793404800,'end':1793404810}]
line='2026-10-31T00:00:01Z level=ERROR msg="Probe failed" target=http://backend-a:8999/health'
assert classify(line,'blackbox',wrong)['classification']=='expected'
assert classify(line.replace('8999','8000'),'blackbox',wrong)['classification']=='unexpected'
assert classify(line.replace('00:00:01Z','00:00:20Z'),'blackbox',wrong)['classification']=='unexpected'
dns='2026-10-31T00:00:01Z level=ERROR msg="Error resolving address" target=http://backend-a:8000/health'
assert classify(dns,'blackbox',window)['classification']=='expected'
assert classify(dns.replace('00:00:01Z','00:00:20Z'),'blackbox',window)['classification']=='unexpected'
failed=[{'kind':'primary-off','start':1793404800,'end':1793404860,'failover_status':'failed'}]
gateway='2026-10-31T00:00:20Z level=ERROR msg="Invalid HTTP response status code" target=http://gateway:8080/health status_code=503'
assert classify(gateway,'blackbox',failed)['related_check']=='FAILOVER'
assert classify(gateway,'blackbox',[{**failed[0],'failover_status':'passed'}])['classification']=='unexpected'

# A valid toolbox is the positive control for every isolation mutation below.
from copy import deepcopy
from run import Runner
project = Path(__file__).resolve().parents[1]
safe_config = {
    'networks': {'control': {'internal': True}},
    'services': {'toolbox': {
        'networks': {'control': None},
        'cap_drop': ['ALL'],
        'security_opt': ['no-new-privileges:true'],
        'mem_limit': '134217728',
        'cpus': 0.5,
        'build': {'context': str(project)},
        'volumes': [{'type': 'bind', 'source': str(project), 'target': '/workspace'}],
    }},
}
def assert_safety(config, accepted):
    runner = Runner.__new__(Runner)
    runner.project, runner.n, runner.config = project, 3, config
    try:
        runner.safety()
    except AssertionError:
        assert not accepted, 'The positive isolation control was rejected'
    else:
        assert accepted, 'Unsafe toolbox configuration was accepted'

assert_safety(safe_config, True)
for field, value in [('cap_drop', []), ('security_opt', []), ('mem_limit', 0), ('cpus', 0)]:
    changed = deepcopy(safe_config)
    changed['services']['toolbox'][field] = value
    assert_safety(changed, False)
for field in ('cap_drop', 'security_opt', 'mem_limit', 'cpus'):
    changed = deepcopy(safe_config)
    changed['services']['toolbox'].pop(field)
    assert_safety(changed, False)
for field in ('mem_limit', 'cpus'):
    for value in (-1, 'nan', 'not-a-limit'):
        changed = deepcopy(safe_config)
        changed['services']['toolbox'][field] = value
        assert_safety(changed, False)
changed = deepcopy(safe_config)
changed['networks']['control']['internal'] = False
assert_safety(changed, False)
changed = deepcopy(safe_config)
changed['services']['toolbox']['networks'] = {'control': None, 'extra': None}
assert_safety(changed, False)
print('TOOLBOX_SAFETY_NEGATIVE_CONTROLS_OK; internal network, capabilities, privileges, RAM, CPU, membership')

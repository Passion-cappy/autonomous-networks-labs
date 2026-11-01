"""A supplied API test client, not a network controller. It never applies recommendations."""
import json,os,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
RESULTS=Path(os.environ.get('NETLAB_EVIDENCE_DIR','results'))
SCHEMA={'type':'object','properties':{
 'assessment':{'type':'string','enum':['hypothesis','insufficient_evidence']},
 'summary':{'type':'string'},'probable_causes':{'type':'array','items':{'type':'string'},'maxItems':8},
 'evidence_ids':{'type':'array','items':{'type':'string'},'maxItems':8},
 'recommended_checks':{'type':'array','items':{'type':'string'},'maxItems':8}},
 'required':['assessment','summary','probable_causes','evidence_ids','recommended_checks'],'additionalProperties':False}
def fetch(url,payload=None,timeout=5):
    req=Request(url,json.dumps(payload).encode() if payload is not None else None,{'Content-Type':'application/json'})
    with urlopen(req,timeout=timeout) as r:return json.load(r)
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def validate(value,evidence):
    if not isinstance(value,dict) or set(value)!=set(SCHEMA['required']):raise ValueError('Unexpected analysis fields')
    if value['assessment'] not in ('hypothesis','insufficient_evidence') or not isinstance(value['summary'],str):raise ValueError('Invalid assessment')
    for key in ('probable_causes','evidence_ids','recommended_checks'):
        if not isinstance(value[key],list) or len(value[key])>8 or not all(isinstance(x,str) for x in value[key]):raise ValueError('Invalid list '+key)
    if not set(value['evidence_ids']).issubset({x['id'] for x in evidence['evidence']}):raise ValueError('Unknown evidence ID')
    return value
def snapshot(limited=False):
    data={'observed_at':datetime.now(timezone.utc).isoformat(),'limited_evidence':limited,'evidence':[]}
    if limited:
        data['evidence']=[{'id':'E1','source':'student observation','observation':'A service problem was reported; no measurements were supplied.'}]
    else:
        samples=fetch('http://prometheus:9090/api/v1/query?query=probe_success')['data']['result']
        from urllib.parse import urlencode
        timestamps=fetch('http://prometheus:9090/api/v1/query?'+urlencode({'query':'timestamp(probe_success)'}))['data']['result']
        at={x['metric']['instance']:float(x['value'][1]) for x in timestamps}
        targets={'http://gateway:8080/health','http://backend-a:8000/health'}
        probes=[{'target':x['metric']['instance'],'value':x['value'][1],'sample_at_unix':at.get(x['metric']['instance']), 'source':'blackbox'} for x in samples if x['metric']['instance'] in targets]
        data['evidence'].append({'id':'E1','source':'prometheus blackbox HTTP probes','observation':probes})
        try:
            raw=fetch('http://events:8001/events')[-2:]
            alerts=[{'at':e['at'],'alerts':[{'status':a['status'],'name':a['labels'].get('alertname'),'target':a['labels'].get('instance')} for a in e['payload']['alerts'][:3]]} for e in raw]
        except OSError:alerts=[]
        data['evidence'].append({'id':'E2','source':'Alertmanager notifications','observation':alerts})
        p=RESULTS/'backend-a.log';lines=p.read_text(encoding='utf-8').splitlines()[-3:] if p.exists() else []
        data['evidence'].append({'id':'E3','source':'backend-a HTTP log','observation':[x[:200] for x in lines]})
    return data
def main(mode):
    root=RESULTS/'incidents';root.mkdir(parents=True,exist_ok=True)
    if mode=='incident':
        identifier=(RESULTS/'latest-incident.txt').read_text(encoding='utf-8').strip()
        assert identifier.isalnum();folder=root/identifier;evidence=json.loads((folder/'evidence.json').read_text(encoding='utf-8'))
    else:
        identifier=uuid.uuid4().hex;folder=root/identifier;folder.mkdir()
        evidence=snapshot(mode=='limited');write(folder/'evidence.json',evidence)
    if mode=='snapshot':
        (RESULTS/'latest-incident.txt').write_text(identifier,encoding='utf-8');print('INCIDENT_SNAPSHOT_OK '+identifier);return {'incident_id':identifier}
    result={'incident_id':identifier,'analysis_status':'unavailable','executed_actions':[],'model':os.getenv('MODEL','qwen3:0.6b')}
    started=time.monotonic()
    try:
        deadline=time.monotonic()+float(os.getenv('NETLAB_AI_READINESS_TIMEOUT','60'))
        while True:
            try:version=fetch('http://ollama:11434/api/version');break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(1)
        models=fetch('http://ollama:11434/api/tags')['models']
        local=next((m for m in models if m['name']==result['model']),None)
        assert local is not None,'Model must be present in the local Ollama store'
        result['ollama_version']=version;result['local_model_digest']=local['digest']
        prompt=Path('config/ai-prompt.txt').read_text(encoding='utf-8')
        assert 'TODO' not in prompt and len(prompt.strip())>40,'Write the read-only diagnostic instruction'
        payload={'model':result['model'],'stream':False,'think':False,'format':SCHEMA,
          'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(evidence,ensure_ascii=False)}],
          'options':{'temperature':0,'num_ctx':2048,'num_predict':256,'num_thread':2,'num_gpu':0},'keep_alive':'2m'}
        raw=fetch('http://ollama:11434/api/chat',payload,timeout=150);write(folder/'raw-response.json',raw)
        try:
            result['analysis']=validate(json.loads(raw['message']['content']),evidence);result['analysis_status']='completed'
        except (KeyError,TypeError,ValueError) as e:result.update(analysis_status='invalid_output',error=str(e))
    except Exception as e:result['error']=type(e).__name__+': '+str(e)[:250]
    result['elapsed_seconds']=round(time.monotonic()-started,3);write(folder/'analysis.json',result)
    report='---\nid: incident-'+identifier+'\ntype: runtime-report\ndiscipline: proektuvannia-avtonomykh-merezh\nstatus: draft\n---\n\n# Incident '+identifier+'\n\n```json\n'+json.dumps(result,ensure_ascii=False,indent=2)+'\n```\n\nCheck facts, hypotheses and unsupported claims against evidence.json. No actions were executed.\n'
    (folder/'report.md').write_text(report,encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['analysis_status']=='completed':print('LOCAL_OLLAMA_OK '+identifier)
    return result
if __name__=='__main__':
    mode=sys.argv[1] if len(sys.argv)>1 else 'normal'
    if mode not in ('normal','snapshot','incident','limited'):raise SystemExit('Use normal, snapshot, incident or limited')
    value=main(mode)
    if mode!='snapshot' and value['analysis_status']!='completed':raise SystemExit('LOCAL_AI_NOT_COMPLETED; preserve the evidence')

"""Preserve service logs and classify only explicitly timed, known fault messages."""
import json,re
from datetime import datetime,timezone

ERROR = re.compile(r'Traceback|Exception occurred|ConnectionResetError|BrokenPipeError|\[(?:ALERT|FATAL)\]|\blevel[=:]\s*["\']?(?:error|fatal)\b|"level"\s*:\s*"ERROR"',re.I)

def classify(line, service, windows):
    match=re.match(r'(\S+)\s+(.*)',line)
    at=None
    if match:
        try:at=datetime.fromisoformat(match[1].replace('Z','+00:00')).timestamp()
        except ValueError:pass
    if not ERROR.search(line):return None
    for window in windows:
        if at is None or not window['start']<=at<=window['end']:continue
        known=False
        if service=='gateway' and window['kind']=='primary-off' and 'has no server available' in line:known=True
        if service=='blackbox' and any(message in line for message in ('msg="Error for HTTP request"','msg="Probe failed"','msg="Resolution with IP protocol failed"','msg="Error resolving address"','msg="Invalid HTTP response status code"')):
            if window['kind']=='wrong-port' and 'target=http://backend-a:8999/health' in line:known=True
            if window['kind']=='primary-off' and 'target=http://backend-a:8000/health' in line:known=True
            if window['kind']=='primary-off' and 'target=http://gateway:8080/health' in line and at<=window['start']+10:known=True
            if window['kind']=='primary-off' and 'target=http://gateway:8080/health' in line and window.get('failover_status')=='failed':
                return {'classification':'explained_failure','related_check':'FAILOVER','scenario':window['kind'],'line':line}
        if known:return {'classification':'expected','scenario':window['kind'],'line':line}
    return {'classification':'unexpected','line':line}

def collect(config, command, output, since, windows=(), omitted=()):
    output.mkdir(parents=True,exist_ok=True)
    result={'schema':1,'since':datetime.fromtimestamp(since,timezone.utc).isoformat(),'windows':list(windows),'services':{},'unexpected':[],'expected':[],'explained_failure':[]}
    for service in sorted(config['services']):
        if service in omitted:continue
        rows=command(['docker','ps','-aq','--filter','label=com.docker.compose.project='+config['name'],'--filter','label=com.docker.compose.service='+service]).stdout.split()
        if not rows:
            result['unexpected'].append({'service':service,'issue':'required service has no container'})
            continue
        info=json.loads(command(['docker','inspect',rows[0]]).stdout)[0]
        state={k:info['State'].get(k) for k in ('Status','Running','ExitCode','OOMKilled','Error','StartedAt','FinishedAt')}
        state['HealthStatus']=info['State'].get('Health',{}).get('Status')
        raw=command(['docker','logs','--timestamps','--since',str(int(since)),rows[0]],allowed=(0,1))
        text=raw.stdout+raw.stderr
        (output/(service+'.log')).write_text(text,encoding='utf-8')
        result['services'][service]={'state':state,'image':info['Config']['Image'],'log':service+'.log'}
        if raw.returncode!=0:
            result['unexpected'].append({'service':service,'issue':'service logs could not be collected','exit_code':raw.returncode})
        if not state['Running'] or state['OOMKilled'] or state['HealthStatus']=='unhealthy':
            result['unexpected'].append({'service':service,'issue':'service not healthy after the experiment','state':state})
        for line in text.splitlines():
            value=classify(line,service,windows)
            if value:result[value['classification']].append({'service':service,**value})
    (output/'diagnostics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result

"""Read-only Docker Hub freshness check. Updates require review and protocol replay."""
import json,re,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen
LOCK=Path(__file__).with_name('images.lock.json')
def fetch(url):
    with urlopen(url,timeout=30) as f:return json.load(f)
def main():
    lock=json.loads(LOCK.read_text(encoding='utf-8'));out=[];changed=False
    for key,item in lock['images'].items():
        base='https://hub.docker.com/v2/repositories/'+item['hub_repository']+'/tags/'
        tracking=item['tracking']
        if tracking.startswith('prefix:'):
            prefix=tracking[7:];values=fetch(base+'?page_size=100&name='+prefix)['results']
            candidates=[v for v in values if re.fullmatch(r'v?\d+\.\d+\.\d+',v['name']) and v['name'].startswith(prefix)]
            if not candidates:raise RuntimeError('No supported branch tag found for '+key)
            current=max(candidates,key=lambda v:tuple(map(int,re.findall(r'\d+',v['name']))))
        else:current=fetch(base+tracking)
        different=current['digest']!=item['digest'];changed|=different
        out.append({'image':key,'pinned_tag':item['tag'],'tracking':tracking,'upstream_last_updated':current['last_updated'],'digest_changed':different,'candidate_digest':current['digest']})
    age=(datetime.now(timezone.utc).date()-datetime.fromisoformat(lock['checked_at']).date()).days
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'support_policy_review_due':age>lock['review_interval_days'],'changes':out,'cve_scan_performed':False}
    print(json.dumps(result,indent=2))
    return 3 if changed or result['support_policy_review_due'] else 0
if __name__=='__main__':raise SystemExit(main())

"""Test notification receiver; no model access or configuration-changing endpoint."""
import json,threading
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
OUT=Path('results/alerts.jsonl');LOCK=threading.Lock()
class Handler(BaseHTTPRequestHandler):
    def reply(self,code,value):
        body=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path!='/events':return self.reply(404,{})
        lines=OUT.read_text(encoding='utf-8').splitlines()[-100:] if OUT.exists() else []
        self.reply(200,[json.loads(x) for x in lines])
    def do_POST(self):
        if self.path!='/alerts':return self.reply(404,{})
        try:
            size=int(self.headers.get('Content-Length','0'));assert 0<size<=65536
            value=json.loads(self.rfile.read(size));assert isinstance(value.get('alerts'),list)
        except (ValueError,AssertionError,AttributeError):return self.reply(400,{'error':'invalid_alert'})
        with LOCK:
            OUT.parent.mkdir(exist_ok=True)
            if OUT.exists() and OUT.stat().st_size>1048576:OUT.replace(OUT.with_suffix('.previous.jsonl'))
            with OUT.open('a',encoding='utf-8') as f:f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'payload':value})+'\n')
        self.reply(200,{'received':True})
if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',8001),Handler).serve_forever()

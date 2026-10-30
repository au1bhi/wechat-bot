import json,os,subprocess,sys,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def serve(status):
    class H(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            if self.path=='/vnc.html':
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok');return
            ok=self.headers.get('Authorization')=='Bearer secret'
            body=json.dumps(status if ok else {'error':'UNAUTHORIZED'}).encode()
            self.send_response(200 if ok else 401);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=HTTPServer(('127.0.0.1',0),H)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


class Health(unittest.TestCase):
    def run_check(self,status):
        server=serve(status)
        with tempfile.NamedTemporaryFile('w',suffix='.token') as token:
            token.write('secret\n');token.flush()
            url='http://127.0.0.1:%d/'%server.server_port
            env={**os.environ,'HEALTH_BRIDGE':url,'HEALTH_VNC':url+'vnc.html','HEALTH_TOKEN_FILE':token.name}
            result=subprocess.run([sys.executable,str(ROOT/'healthcheck.py')],env=env,capture_output=True,text=True,timeout=20)
        server.shutdown()
        return result

    def test_logged_in_is_healthy(self):
        self.assertEqual(self.run_check({'ok':True,'logged_in':True,'locked':False}).returncode,0)

    def test_logged_out_locked_or_broken_bridge_is_unhealthy(self):
        for status,text in (({'ok':True,'logged_in':False},'logged out'),({'ok':True,'logged_in':True,'locked':True},'locked'),({'ok':False,'error':'WAITING_FOR_WECHAT'},'WAITING_FOR_WECHAT')):
            r=self.run_check(status);self.assertEqual(r.returncode,1);self.assertIn(text,r.stderr)


if __name__=='__main__':unittest.main()

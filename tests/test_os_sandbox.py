import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT))
import model_sandbox as sandbox


@unittest.skipUnless(os.environ.get('RUN_OS_SANDBOX_TESTS')=='1','Enable for actual namespace/network tests')
class KernelBoundary(unittest.TestCase):
    def test_host_files_processes_sockets_and_network_are_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            canary=root/'private-host-canary';canary.write_text('HOST_ONLY_PRIVATE_CANARY')
            binary=root/'probe'
            subprocess.run(['gcc','-static','-O2','-Wall','-Wextra','-Werror',str(ROOT/'tests/sandbox_probe.c'),'-o',str(binary)],check=True)
            server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1)
            port=server.getsockname()[1]
            cfg={'codex_bin':str(binary),'network_guard_bin':str(ROOT/'bin/net-guard')}
            fds=[]
            try:
                auth=sandbox.memfile('dummy-login',b'{"dummy":true}');fds.append(auth)
                schema=sandbox.memfile('dummy-schema',b'{}');fds.append(schema)
                options=sandbox.sandbox_options(cfg,auth,schema)
                args=sandbox.memfile('options',b'\0'.join(x.encode() for x in options)+b'\0');fds.append(args)
                command=['/usr/bin/bwrap','--args',str(args),'--','/bin/net-guard','/bin/codex',
                         str(canary),str(Path.home()/'.codex/auth.json'),str(os.getpid()),str(port)]
                env={**os.environ,'HOST_PRIVATE_CANARY':'must-not-be-inherited'}
                result=subprocess.run(command,text=True,capture_output=True,pass_fds=tuple(fds),env=env,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                observed=json.loads(result.stdout)
                for key in ['canary','private_home','host_process','shell','docker','dbus','cpu_info','leaked_env','connected']:
                    self.assertFalse(observed[key],key)
                self.assertEqual(observed['hostname'],'chat-sandbox')
                self.assertEqual(observed['network_errno'],13)  # EACCES, not an absent server.
            finally:
                server.close()
                for fd in fds:os.close(fd)


if __name__=='__main__':unittest.main()

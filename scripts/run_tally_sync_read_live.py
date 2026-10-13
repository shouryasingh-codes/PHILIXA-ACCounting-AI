"""Windows-only bridge acceptance runner; secrets stay in memory/stdin."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import httpx
from helper import connect

def main():
    base='http://127.0.0.1:8001/api/v1/integrations/tally'
    with tempfile.TemporaryDirectory(dir='.helper-build') as temp:
        connect.HOME=Path(temp)
        with httpx.Client(timeout=30,trust_env=False) as client:
            pairing=client.post(base+'/pairing/begin').json()
        stopped=threading.Event()
        def poll():
            with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+pairing['credential']},trust_env=False) as client:
                while not stopped.is_set():
                    try:
                        response=client.get(base+'/helper/jobs',params={'protocol_version':2})
                        if response.status_code!=200:stopped.wait(.2);continue
                        job=response.json()['job']
                        if job:
                            try:payload={'id':job['id'],'data':connect.execute(job,9000)}
                            except Exception:payload={'id':job['id'],'error':'Read failed'}
                            client.post(base+'/helper/results',json=payload)
                        else:stopped.wait(.2)
                    except httpx.HTTPError:stopped.wait(.5)
        worker=threading.Thread(target=poll);worker.start()
        try:
            docker=Path(os.environ['LOCALAPPDATA'])/'Programs/DockerDesktop/resources/bin/docker.exe'
            result=subprocess.run([str(docker),'compose','exec','-T','app','python','-m','scripts.verify_tally_sync_read_live'],
                input=json.dumps({'code':pairing['code']})+'\n',text=True,capture_output=True,timeout=150)
            print(result.stdout)
            if result.returncode:
                print(result.stderr);raise SystemExit(result.returncode)
        finally:stopped.set();worker.join(timeout=35)
if __name__=='__main__':main()

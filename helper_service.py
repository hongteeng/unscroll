"""Install/remove a per-user local processing helper on the owner's Mac."""
import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL='local.unscroll.helper'


def service_spec(root,python,logs):
    return {'Label':LABEL,'ProgramArguments':[str(python),'-m','uvicorn','unscroll.server:app','--host','127.0.0.1','--port','8765'],
            'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':20,
            'StandardOutPath':str(logs/'helper.log'),'StandardErrorPath':str(logs/'helper-error.log'),
            'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['install','remove']);args=parser.parse_args()
    if sys.platform!='darwin':raise SystemExit('This helper manager runs only on macOS.')
    root=Path(__file__).resolve().parent
    plist=Path.home()/'Library'/'LaunchAgents'/(LABEL+'.plist')
    domain=f'gui/{os.getuid()}'
    if args.action=='remove':
        subprocess.run(['launchctl','bootout',domain+'/'+LABEL],check=False)
        plist.unlink(missing_ok=True)
        print('Automatic helper startup removed. Your library and downloads were kept.')
        return
    python=root/'.venv'/'bin'/'python'
    if not python.exists():raise SystemExit('Run Setup.command first.')
    logs=Path.home()/'Library'/'Logs'/'Unscroll';logs.mkdir(parents=True,exist_ok=True,mode=0o700)
    plist.parent.mkdir(parents=True,exist_ok=True)
    with plist.open('wb') as f:plistlib.dump(service_spec(root,python,logs),f)
    os.chmod(plist,0o600)
    subprocess.run(['launchctl','bootout',domain+'/'+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    result=subprocess.run(['launchctl','bootstrap',domain,str(plist)],capture_output=True,text=True)
    if result.returncode:
        raise SystemExit('macOS could not enable the helper. Open Start.command for manual startup. '+result.stderr.strip())
    print('Unscroll helper enabled for this login and future logins.')


if __name__=='__main__':main()

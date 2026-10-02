import argparse,os,plistlib,subprocess
from pathlib import Path
from app.config import ROOT
LABEL='com.neura.hermes-telegram-bot'
PLIST=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
DOMAIN=f'gui/{os.getuid()}'
def run(*args,check=True):return subprocess.run(['launchctl',*args],check=check,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['install','start','stop','restart','status','uninstall']);a=p.parse_args().action
 if a=='install':
  PLIST.parent.mkdir(parents=True,exist_ok=True)
  data={'Label':LABEL,'ProgramArguments':[str(ROOT/'.venv/bin/python'),'-m','app'],
    'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
    'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/bin:/bin','PYTHONUNBUFFERED':'1','PYTHONNOUSERSITE':'1'},
    'StandardOutPath':str(ROOT/'logs/launchd.out.log'),'StandardErrorPath':str(ROOT/'logs/launchd.err.log')}
  PLIST.write_bytes(plistlib.dumps(data));PLIST.chmod(0o600)
  run('bootout',DOMAIN,str(PLIST),check=False);r=run('bootstrap',DOMAIN,str(PLIST),check=False)
  if r.returncode:raise SystemExit(r.stderr)
  print('Installed',LABEL)
 elif a=='stop':run('bootout',DOMAIN,str(PLIST),check=False);print('Stopped',LABEL)
 elif a=='uninstall':run('bootout',DOMAIN,str(PLIST),check=False);PLIST.unlink(missing_ok=True);print('Service removed; project and data preserved')
 elif a=='start':
  r=run('bootstrap',DOMAIN,str(PLIST),check=False)
  if r.returncode:run('kickstart',f'{DOMAIN}/{LABEL}')
 elif a=='restart':run('kickstart','-k',f'{DOMAIN}/{LABEL}')
 elif a=='status':
  r=run('print',f'{DOMAIN}/{LABEL}',check=False)
  if r.returncode:print('Service not loaded');raise SystemExit(1)
  for line in r.stdout.splitlines():
   if any(k in line for k in ('state =','pid =','last exit code =','runs =')):print(line.strip())
if __name__=='__main__':main()

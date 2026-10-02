import asyncio,json,os,shutil,sys,tempfile,subprocess
from pathlib import Path
from telegram import Bot
from app.config import Config,ROOT
from app.hermes import HermesClient
from app.storage import Storage
from app.media import Transcriber

async def diagnose():
 c=Config.load();h=HermesClient(c);s=await Storage().open();checks={}
 checks['Python venv']='OK · '+sys.version.split()[0] if sys.prefix!=sys.base_prefix else 'ERROR'
 checks['Secrets permissions']='OK' if (ROOT/'.env').stat().st_mode & 0o077 == 0 else 'ERROR'
 checks['OWNER']='OK · '+str(c.owner)
 try:
  async with Bot(c.token) as bot:
   me=await bot.get_me();checks['Telegram']='OK · @'+me.username
   commands=await bot.get_my_commands();checks['Command menu']='OK · '+str(len(commands))+' comandos'
 except Exception as e:checks['Telegram']='ERROR · '+type(e).__name__
 for name,fn in [('Hermes backend',h.health),('Chats API',h.chats),('Profiles API',h.profiles),('Bots/personalities API',lambda:h.personalities('default')),('Models API',lambda:h.models('default')),('Tools API',lambda:h.tools('default'))]:
  try:
   d=await fn();checks[name]='OK'+(' · '+str(len(d)) if isinstance(d,list) else '')
  except Exception as e:checks[name]='ERROR · '+type(e).__name__
 for profile in await h.profiles():
  try:
   await h.native.request('GET','/api/sessions',profile['name'],params={'title':'Bot Chat','include_hidden':'true'})
   checks['Bot API '+profile['name']]='OK'
  except Exception as e:checks['Bot API '+profile['name']]='ERROR · '+type(e).__name__
 try:
  await s.get('doctor');checks['Database']='OK'
  async with s.db.execute('SELECT kind,count FROM metrics') as cur:checks['Counters']=dict(await cur.fetchall())
  async with s.db.execute('SELECT count(*) FROM updates WHERE status="processing"') as cur:checks['Pending requests']=(await cur.fetchone())[0]
 except Exception:checks['Database']='ERROR'
 try:
  with tempfile.TemporaryFile(dir=ROOT/'data/tmp') as f:f.write(b'probe')
  checks['Temporary storage']='OK'
 except OSError:checks['Temporary storage']='ERROR'
 try:
  t=Transcriber(c,h);await t.ready();checks['Transcription']='OK · '+c.engine+' · '+c.model+' · '+c.language
 except Exception as e:checks['Transcription']='ERROR · '+type(e).__name__
 checks['ffmpeg']='OK' if shutil.which('ffmpeg') or Path('/opt/homebrew/bin/ffmpeg').exists() else 'ERROR'
 proc=await asyncio.create_subprocess_exec('launchctl','print',f'gui/{os.getuid()}/com.neura.hermes-telegram-bot',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
 out,_=await proc.communicate();checks['launchd']='OK · running' if b'state = running' in out else 'NOT RUNNING'
 report=ROOT/'docs/validation.json'
 if report.exists():checks['Controlled E2E']=json.loads(report.read_text())
 else:checks['Controlled E2E']='PENDING'
 checks['Image input']='Supported · native multimodal or Hermes vision tool according to profile'
 checks['File input']='Supported · original upload + Hermes file/tools (format-dependent parsing)'
 checks['Native audio']='File/tool input; navigation uses local transcript'
 checks['Limits']='Telegram cloud: inbound 20 MB; outbound 50 MB; audio 7200s'
 await h.close();await s.close();return checks
async def main():
 result=await diagnose()
 for k,v in result.items():print(k+' → '+(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v)))
 if any(isinstance(v,str) and v.startswith('ERROR') for v in result.values()):raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())

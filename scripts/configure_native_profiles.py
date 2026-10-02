"""Provision missing profile-scoped local API keys, without replacing existing keys."""
import asyncio,fcntl,json,os,secrets
from pathlib import Path
from dotenv import dotenv_values
from app.config import Config,ROOT
from app.hermes import HermesClient

def provision_key(env_path):
    # Lock the original file and append only the missing setting. Preserve all
    # existing provider/platform settings and never inherit another bot's key.
    env_path=Path(env_path)
    with env_path.open('a+',encoding='utf-8') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        handle.seek(0)
        text=handle.read()
        import io
        if dotenv_values(stream=io.StringIO(text)).get('API_SERVER_KEY'):
            return False
        handle.seek(0,os.SEEK_END)
        handle.write(('\n' if text and not text.endswith('\n') else '')+
                     '\n# Local Hermes API authentication for Telegram client\n'+
                     'API_SERVER_KEY='+secrets.token_urlsafe(48)+'\n')
        handle.flush();os.fsync(handle.fileno());os.fchmod(handle.fileno(),0o600)
        return True

async def main():
    h=HermesClient(Config.load());report=[]
    try:
        for bot in await h.bots():
            name=bot['name'];home=Path(bot['path']).resolve()
            if home!=h.native.home(name).resolve():
                raise ValueError('Unexpected profile home')
            configured=await asyncio.to_thread(provision_key,home/'.env')
            # Real API read validates auth, routing and the canonical session.
            chat=await h.bot_chat(name)
            report.append({'profile':name,'key_added':configured,'canonical_session':chat['session_id'],'status':'PASS'})
            print(name+' → PASS'+(' · local API configured' if configured else ' · existing key preserved'),flush=True)
        (ROOT/'docs/all-bots-validation.json').write_text(json.dumps({'status':'PASS','bots':report},indent=2))
    finally:await h.close()

if __name__=='__main__':asyncio.run(main())

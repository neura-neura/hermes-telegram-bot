"""Check published assets and real Telegram acceptance of HTTPS bridge buttons."""
import asyncio,hashlib,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit,unquote
import httpx
from telegram import Bot
from app.bot import Gateway
from app.config import Config,ROOT
from app.storage import Storage
from app.obsidian import extract_obsidian_telegram_actions,obsidian_button_url

async def main():
 c=Config.load();g=Gateway(c);await g.store.open()
 if not c.obsidian_bridge_url:raise ValueError('Configure OBSIDIAN_BRIDGE_URL first')
 report={'bridge_url':c.obsidian_bridge_url}
 try:
  async with httpx.AsyncClient(timeout=30,follow_redirects=True) as client:
   for name in ('index.html','bridge.js','style.css'):
    r=await client.get(c.obsidian_bridge_url+name);r.raise_for_status()
    assert r.content==(ROOT/'bridge'/name).read_bytes(),name
   report['published_assets_match']=True
  # Prefer a real URI from the OWNER's current Hermes session. Never print it.
  uri=None
  try:
   _,session=await g.active(f'{c.owner}:0:{c.owner}')
   for message in reversed((session or {}).get('messages',[])):
    content=message.get('content','')
    if isinstance(content,str):
     actions=extract_obsidian_telegram_actions(content)
     if actions['buttons']:uri=actions['buttons'][0]['url'];break
  except Exception:pass
  real_note=uri is not None
  uri=uri or 'obsidian://open?vault=Hermes%20Prueba&file=Carpeta/Nota%20de%20prueba'
  scope=f'{c.owner}:0:{c.owner}'
  # Use a disposable mapping DB: keep the real user's chat selection untouched.
  await g.store.close()
  with tempfile.TemporaryDirectory() as tmp:
   g.store=await Storage().open(Path(tmp)/'state.db')
   async with Bot(c.token) as bot:
    received=[]
    async def reply(text,**kwargs):
     m=await bot.send_message(c.owner,text,**kwargs);received.append(m);return m
    u=SimpleNamespace(effective_chat=SimpleNamespace(id=c.owner),effective_user=SimpleNamespace(id=c.owner),effective_message=SimpleNamespace(message_thread_id=None,reply_text=reply))
    description=('Prueba del puente: este botón apunta a una nota de tu conversación actual.' if real_note else 'Prueba técnica del puente: vault y nota ficticios. El botón debe abrir Obsidian, aunque esta nota no exista.')
    await g.deliver(u,description+'\n[Abrir en Obsidian]('+uri+')','bridge-probe','default')
    button=received[0].reply_markup.inline_keyboard[0][0]
    assert button.text=='Abrir en Obsidian'
    assert button.url==obsidian_button_url(uri,c.obsidian_bridge_url)
    assert unquote(urlsplit(button.url).fragment)==uri
    assert '[Abrir en Obsidian]' not in received[0].text
    report.update(telegram_button_accepted=True,original_uri_preserved=True,real_note_used=real_note,message_id=received[0].message_id,uri_sha256=hashlib.sha256(uri.encode()).hexdigest(),phone_opening='Requires user verification')
   (ROOT/'docs/obsidian-bridge-validation.json').write_text(json.dumps(report,indent=2))
   print(json.dumps(report,indent=2))
 finally:await g.store.close();await g.hermes.close()

if __name__=='__main__':asyncio.run(main())

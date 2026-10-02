"""Real Bot API compatibility probe and gateway fallback delivery to OWNER."""
import asyncio,json,logging,tempfile
from pathlib import Path
from types import SimpleNamespace
from telegram import Bot,MessageEntity
from telegram.error import BadRequest
from app.bot import Gateway
from app.config import Config,ROOT
from app.storage import Storage
URI='obsidian://open?vault=Hermes%20Prueba&file=Carpeta/Nota%20de%20prueba'

async def main():
 c=Config.load();c.obsidian_bridge_url='';g=Gateway(c);result={'uri':URI,'desktop_modified':False}
 with tempfile.TemporaryDirectory() as tmp:
  g.store=await Storage().open(Path(tmp)/'state.db')
  try:
   async with Bot(c.token) as bot:
    attempts=[]
    async def reply(text,**kwargs):
     try:
      m=await bot.send_message(c.owner,text,**kwargs)
      attempts.append({'keyboard':bool(kwargs.get('reply_markup')),'accepted':True,'message_id':m.message_id})
      return m
     except BadRequest as e:
      # Fixed probe URI only; do not record arbitrary model content.
      attempts.append({'keyboard':bool(kwargs.get('reply_markup')),'accepted':False,'reason':str(e)})
      raise
    u=SimpleNamespace(effective_chat=SimpleNamespace(id=c.owner),effective_user=SimpleNamespace(id=c.owner),effective_message=SimpleNamespace(message_thread_id=None,reply_text=reply))
    await g.deliver(u,'Prueba de compatibilidad Obsidian:\n[Abrir en Obsidian]('+URI+')','obsidian-probe','default')
    result['gateway_attempts']=attempts
    try:
     msg=await bot.send_message(c.owner,'Abrir en Obsidian',entities=[MessageEntity('text_link',0,len('Abrir en Obsidian'),url=URI)])
     result['text_link_entity']={'accepted':True,'message_id':msg.message_id,'returned_entities':[{'type':e.type,'url':e.url} for e in msg.entities]}
    except BadRequest as e:result['text_link_entity']={'accepted':False,'reason':str(e)}
    result['fallback_delivered']=any(a['accepted'] and not a['keyboard'] for a in attempts)
    result['inline_button_accepted']=any(a['accepted'] and a['keyboard'] for a in attempts)
    (ROOT/'docs/obsidian-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
  finally:await g.store.close();await g.hermes.close()

if __name__=='__main__':asyncio.run(main())

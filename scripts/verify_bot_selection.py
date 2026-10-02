import asyncio,time,json
from types import SimpleNamespace
from telegram import Bot,Message
from app.bot import Gateway
from app.config import Config,ROOT
async def main():
 c=Config.load();g=Gateway(c);await g.store.open()
 try:
  async with Bot(c.token) as bot:
   m=Message.de_json({'message_id':1,'date':int(time.time()),'chat':{'id':c.owner,'type':'private'},'from':{'id':c.owner,'is_bot':False,'first_name':'Owner'}},bot)
   u=SimpleNamespace(effective_message=m,effective_chat=m.chat,effective_user=m.from_user);g.application=SimpleNamespace(bot=bot)
   before=await g.store.get(g.scope(u))
   await g.dispatch(u,{'action':'open','query':'Little K'})
   after=await g.store.get(g.scope(u));assert before['profile']==after['profile']=='default';assert after['bot']=='Little K'
   await g.converse(u,'Hola Little K. Para comprobar la conexión, saluda brevemente e identifica tu nombre. No uses herramientas.',[])
   await bot.send_message(c.owner,'Corregido: Little K quedó seleccionado como bot; tu perfil sigue siendo default. /profiles cambia de perfil explícitamente y /bots abre al bot desde el perfil actual.')
   (ROOT/'docs/bot-selection-validation.json').write_text(json.dumps({'status':'PASS','ui_profile_before':before['profile'],'ui_profile_after':after['profile'],'bot':after['bot'],'bot_owner':after['bot_profile'],'response_delivered':True},indent=2))
   print('Bot selection preserving UI profile PASS',flush=True)
 finally:await g.store.close();await g.hermes.close()
asyncio.run(main())

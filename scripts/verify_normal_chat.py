"""Verify leaving a Bot Chat using the real Hermes API, without a model turn."""
import asyncio,json
from app.bot import Gateway
from app.config import Config,ROOT
from app.routing import intent
async def main():
 g=Gateway(Config.load());await g.store.open();scope=f'{g.config.owner}:0:{g.config.owner}'
 try:
  before=await g.store.get(scope)
  assert intent('sal del bot').action=='create'
  chat=await g.hermes.create(before['profile'])
  await g.store.activate(scope,chat['session_id'],before['profile'])
  after=await g.store.get(scope)
  actual=await g.hermes.chat(after['sid'],after['profile'])
  assert after['profile']==before['profile']
  assert not any(after.get(k) for k in ('bot','bot_profile','bot_native'))
  report={'status':'PASS','profile_before':before['profile'],'profile_after':after['profile'],'previous_bot':before.get('bot'),'new_session':after['sid'],'normal_chat_verified':bool(actual)}
  (ROOT/'docs/normal-chat-validation.json').write_text(json.dumps(report,indent=2))
  print(json.dumps(report))
 finally:await g.store.close();await g.hermes.close()
asyncio.run(main())

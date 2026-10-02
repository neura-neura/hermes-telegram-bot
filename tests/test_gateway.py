import asyncio,io
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.config import Config
from app.storage import Storage
from app.routing import intent,match_name
from app.formatting import split_text,telegram_html,output_paths
from app.media import mime_type,safe_name,MediaGroups,Transcriber
from app.bot import Gateway

@pytest.mark.parametrize('uid,chat,private,expected',[(123,123,True,True),(999,999,True,False),(123,-1,False,False),(123,-2,False,True),(888,-2,False,False)])
def test_permission(uid,chat,private,expected):
 assert Config('fake',123,chats=frozenset([-2])).allowed(uid,chat,private)==expected

def test_owner():
 c=Config('secret',123);assert c.admin(123);assert not c.admin(999);assert 'secret' not in repr(c)

@pytest.mark.parametrize('text,action',[('muéstrame mis bots','bots'),('muéstrame mis chats','chats'),('quiero hablar con Little K','open'),('regresa al anterior','back'),('¿Qué es asyncio?','message'),('abre un chat nuevo','new'),('busca el chat donde hablábamos de Telegram','search')])
def test_intent(text,action):assert intent(text).action==action

def test_combined():
 r=intent('abre Little K y pregúntale qué está haciendo');assert r.query=='Little K';assert r.message=='qué está haciendo'

def test_names():assert len(match_name([{'name':'little-k'}],'Little K'))==1

@pytest.mark.parametrize('text',['a'*10000,'hola 🐈 '*3000,'one\n\ntwo '*2000])
def test_split(text):
 parts=list(split_text(text));assert ''.join(parts)==text
 assert all(len(p.encode('utf-16-le'))//2<=3800 for p in parts)

def test_format():
 assert '&lt;script&gt;' in telegram_html('<script>')
 assert '<b>hola</b>'==telegram_html('**hola**')
 assert '<pre>' in telegram_html('```python\nprint(1)\n```')

def test_paths():assert output_paths('[csv](/tmp/a.csv)\nMEDIA:/tmp/a.png')==['/tmp/a.png','/tmp/a.csv']

def test_mime():
 assert mime_type('image.png','application/octet-stream')=='image/png'
 assert mime_type('file.py')=='text/x-python'
 assert mime_type('audio.ogg').startswith('audio/')
 assert safe_name('../../bad.pdf')=='bad.pdf'

@pytest.mark.asyncio
async def test_storage(tmp_path):
 s=await Storage().open(tmp_path/'state.db')
 try:
  await s.activate('scope','a','default');await s.activate('scope','b','joe')
  assert (await s.back('scope'))['sid']=='a'
  cb=await s.callback('scope',{'action':'delete'});assert len(cb.encode())<64
  assert await s.resolve('other',cb) is None
  assert (await s.resolve('scope',cb,True))['action']=='delete'
  assert await s.resolve('scope',cb) is None
  assert await s.claim(1);assert not await s.claim(1)
  await s.map(123,1,'scope','default','a','99',[{'path':'file.pdf'}])
  assert (await s.lookup(123,1,'scope'))['attachments'][0]['path']=='file.pdf'
  assert await s.lookup(123,1,'other') is None
 finally:await s.close()

@pytest.mark.asyncio
async def test_album():
 c=MediaGroups(.03);results=[]
 async def flush(items):results.append(items)
 for n in (3,1,2):c.add('album',SimpleNamespace(effective_message=SimpleNamespace(message_id=n)),flush)
 await asyncio.sleep(.08)
 assert len(results)==1;assert [x.effective_message.message_id for x in results[0]]==[1,2,3]
 await c.close()

@pytest.mark.asyncio
async def test_audio_normalize(tmp_path):
 import wave
 p=tmp_path/'audio.wav'
 with wave.open(str(p),'w') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(8000);f.writeframes(b'\0'*32000)
 tr=Transcriber(Config('fake',123),None);wav=await tr.normalize(p)
 with wave.open(str(wav)) as f:assert f.getnchannels()==1;assert f.getframerate()==16000
 wav.unlink()

@pytest.mark.asyncio
async def test_transcription_wrapper(tmp_path):
 import wave
 p=tmp_path/'silence.wav'
 with wave.open(str(p),'w') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*32000)
 tr=Transcriber(Config('fake',123),None)
 tr.model=SimpleNamespace(transcribe=lambda *a,**k:(iter([]),SimpleNamespace(language='es')))
 from app.media import Attachment
 assert await tr.transcribe(Attachment(p,'silence.wav','audio/wav',32000))==''
 assert not p.with_name('silence.normalized.wav').exists()

@pytest.mark.asyncio
async def test_keyboard(tmp_path):
 g=Gateway(Config('fake',123));g.store=await Storage().open(tmp_path/'state.db')
 try:
  kb=await g.buttons('scope',[[('Chats',{'action':'chats'})]])
  b=kb.inline_keyboard[0][0];assert len(b.callback_data.encode())<64
  assert (await g.store.resolve('scope',b.callback_data))['action']=='chats'
 finally:await g.store.close();await g.hermes.close()

@pytest.mark.asyncio
async def test_hermes_attachment_contract():
 from app.hermes import HermesClient
 h=HermesClient(Config('fake',123));requests=[]
 async def request(method,path,profile='default',**kwargs):
  requests.append(kwargs['json']);return {'stream_id':'x'}
 h.request=request
 try:
  await h.start('sid','default','Lee el PDF',[{'path':'/hermes/attachments/a.pdf','filename':'a.pdf'}])
  assert '[Attached files: /hermes/attachments/a.pdf]' in requests[0]['message']
  assert requests[0]['attachments'][0]['path']=='/hermes/attachments/a.pdf'
 finally:await h.close()

def test_angle_output():assert output_paths('[file](</tmp/a b.csv>)')==['/tmp/a b.csv']

def test_new_agent_route():assert intent('abre un chat nuevo con Little K').action=='open_new'

@pytest.mark.asyncio
async def test_callback_single_use_concurrent(tmp_path):
 s=await Storage().open(tmp_path/'s.db')
 try:
  key=await s.callback('scope',{'action':'confirm_delete'})
  results=await asyncio.gather(s.resolve('scope',key,True),s.resolve('scope',key,True))
  assert sum(r is not None for r in results)==1
 finally:await s.close()

@pytest.mark.asyncio
async def test_bot_selection_preserves_profile(tmp_path):
 from app.bot import session_profile
 s=await Storage().open(tmp_path/'s.db')
 try:
  await s.activate('scope','normal','default')
  await s.activate_bot('scope','bot-chat','little-k','Little K')
  v=await s.get('scope');assert v['profile']=='default';assert v['bot']=='Little K';assert session_profile(v)=='little-k'
  v=await s.back('scope');assert v['profile']=='default';assert v['sid']=='normal';assert session_profile(v)=='default'
 finally:await s.close()

@pytest.mark.parametrize('text',['sal del bot','abre un chat normal','deja de hablar con el bot y abre una conversación en mi perfil actual'])
def test_exit_bot(text):assert intent(text).action=='create'

@pytest.mark.asyncio
async def test_normal_chat_clears_bot_preserves_profile(tmp_path):
 s=await Storage().open(tmp_path/'s.db')
 try:
  await s.activate('scope','normal','default');await s.activate_bot('scope','bot-chat','little-k','Little K')
  v=await s.get('scope');await s.activate('scope','new-normal',v['profile'])
  v=await s.get('scope');assert v['profile']=='default';assert not v.get('bot_profile');assert not v.get('bot')
  v=await s.back('scope');assert v['sid']=='bot-chat';assert v['bot']=='Little K'
 finally:await s.close()

@pytest.mark.asyncio
async def test_native_reply_mapping_survives_restart(tmp_path):
 path=tmp_path/'s.db';s=await Storage().open(path)
 await s.map(123,1,'scope','little-k','native-id','message-1',native=True)
 await s.close();s=await Storage().open(path)
 try:
  row=await s.lookup(123,1,'scope')
  assert row['native'];assert row['sid']=='native-id';assert row['profile']=='little-k'
 finally:await s.close()

@pytest.mark.asyncio
async def test_exit_and_back_restore_native_transport(tmp_path):
 s=await Storage().open(tmp_path/'s.db')
 try:
  await s.activate_bot('scope','native-id','little-k','Little K')
  v=await s.get('scope');v['bot_native']=True;await s.set('scope',v)
  await s.activate('scope','normal-id',v['profile'])
  v=await s.get('scope');assert not v.get('bot_native');assert v['profile']=='default'
  v=await s.back('scope');assert v['bot_native'];assert v['bot_profile']=='little-k';assert v['profile']=='default'
 finally:await s.close()


def test_profile_api_key_provisioning_preserves_settings(tmp_path):
 from scripts.configure_native_profiles import provision_key
 from dotenv import dotenv_values
 p=tmp_path/'.env';original='PROVIDER_SETTING=keep-me\n'
 p.write_text(original);p.chmod(0o644)
 assert provision_key(p)
 first=p.read_text();key=dotenv_values(p)['API_SERVER_KEY']
 assert first.startswith(original);assert len(key)>=32
 assert p.stat().st_mode & 0o077==0
 assert not provision_key(p);assert p.read_text()==first
 q=tmp_path/'other.env';q.write_text(original)
 assert provision_key(q);assert dotenv_values(q)['API_SERVER_KEY']!=key

@pytest.mark.asyncio
async def test_native_auth_uses_selected_profile_key(tmp_path):
 from app.native import NativeSessions
 n=NativeSessions();n.home=lambda profile:tmp_path/profile
 try:
  for profile in ('default','joe'):
   home=tmp_path/profile;home.mkdir();(home/'.env').write_text('API_SERVER_KEY='+profile+'-test-key-long-enough\n')
  url,headers=await n.auth('joe')
  assert url.endswith('/p/joe');assert headers['Authorization']=='Bearer joe-test-key-long-enough'
  url,headers=await n.auth('default')
  assert '/p/' not in url;assert headers['Authorization']=='Bearer default-test-key-long-enough'
 finally:await n.close()

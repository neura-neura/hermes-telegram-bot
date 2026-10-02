import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from telegram.error import BadRequest
from app.obsidian import extract_obsidian_telegram_actions as extract,valid_obsidian_uri,LABEL
from app.bot import Gateway
from app.config import Config
from app.storage import Storage

URI='obsidian://open?vault=Mi%20Vault&file=Carpeta/Nota%20de%20hoy'

@pytest.mark.parametrize('uri',[URI,'obsidian://open?vault=%E6%88%91%E7%9A%84&file=%E7%AC%94%E8%AE%B0/%C3%B1','obsidian://open?file=A/B/C.md&vault=Vault','obsidian://open?vault=A&file=a%2Bb'])
def test_valid_exact_destination(uri):
 assert valid_obsidian_uri(uri)
 result=extract(uri)
 assert result=={'text':'','buttons':[{'text':LABEL,'url':uri}]}

@pytest.mark.parametrize('uri',[
 'https://open?vault=A&file=B','javascript:alert(1)',
 'obsidian://evil?vault=A&file=B','obsidian://open?file=B',
 'obsidian://open?vault=A','obsidian://open?vault=&file=B',
 'obsidian://open?vault=A&file=','obsidian://open?vault=A&file=a+b',
 'obsidian://open?vault=A&file=B&extra=C','obsidian://open?vault=A&file=B&file=C',
 'obsidian://open?vault=A&file=...','obsidian://open?vault=A&file=%2E%2E%2E',
 'obsidian://open?vault=A&file=%GG','obsidian://open?vault=A&file=%FF',
 'obsidian://open?vault=A&file=%00','obsidian://open?vault=A&file=%3Cscript%3E',
 'obsidian://open?vault=A&file=笔记','obsidian://open/path?vault=A&file=B',
 'obsidian://user@open?vault=A&file=B','obsidian://open?vault=A&file=B#fragment',
])
def test_reject(uri):assert not valid_obsidian_uri(uri)


def test_markdown_and_duplicate():
 text=f'Una nota: [{LABEL}]({URI})\n{URI}\n[Otro título]({URI})'
 result=extract(text)
 assert len(result['buttons'])==1;assert result['buttons'][0]['url']==URI
 assert result['text']=='Una nota: \n\n'

@pytest.mark.parametrize('code',[f'```text\n{URI}\n```',f'~~~\n{URI}\n~~~',f'```\n{URI}',f'`{URI}`',f'``{URI}``'])
def test_code_unchanged(code):assert extract(code)=={'text':code,'buttons':[]}


def test_no_obsidian_identical():
 text='**Hola** [sitio](https://example.com/a?b=1) <script> & `código`'
 assert extract(text)=={'text':text,'buttons':[]}


def test_label_cannot_choose_destination():
 result=extract(f'[javascript:alert(1)]({URI})')
 assert result['buttons']==[{'text':LABEL,'url':URI}]
 malicious=f'[{URI}](javascript:alert(1))'
 assert extract(malicious)['buttons']==[]

@pytest.mark.asyncio
@pytest.mark.parametrize('edit',[False,True])
@pytest.mark.parametrize('reject',[False,True])
async def test_delivery_button_or_fallback(tmp_path,caplog,edit,reject):
 g=Gateway(Config('fake',123));g.store=await Storage().open(tmp_path/'s.db')
 sent=SimpleNamespace(chat_id=123,message_id=42)
 async def sender(text,**kwargs):
  if reject and kwargs.get('reply_markup'):
   raise BadRequest('Inline keyboard button URL protocol is unsupported')
  return sent
 mock=AsyncMock(side_effect=sender)
 u=SimpleNamespace(effective_chat=SimpleNamespace(id=123),effective_user=SimpleNamespace(id=123),effective_message=SimpleNamespace(message_thread_id=None,reply_text=mock))
 status=SimpleNamespace(edit_text=mock) if edit else None
 text=f'<script>bad</script>\n[{LABEL}]({URI})\n[Web](https://example.com)'
 try:
  with caplog.at_level(logging.WARNING):await g.deliver(u,text,'sid','default',status)
  final=mock.call_args
  assert '&lt;script&gt;' in final.args[0]
  assert '<a href="https://example.com">Web</a>' in final.args[0]
  if reject:
   assert URI in final.args[0].replace('&amp;','&')
   assert 'reply_markup' not in final.kwargs
   assert 'unsupported_url_protocol' in caplog.text
   assert URI not in caplog.text
   assert 'localhost' not in final.args[0] and '127.0.0.1' not in final.args[0]
  else:
   assert '[Abrir en Obsidian]' not in final.args[0]
   button=final.kwargs['reply_markup'].inline_keyboard[0][0]
   assert button.text==LABEL and button.url==URI
 finally:await g.store.close();await g.hermes.close()

@pytest.mark.asyncio
async def test_delivery_without_actions_unchanged(tmp_path):
 g=Gateway(Config('fake',123));g.store=await Storage().open(tmp_path/'s.db')
 mock=AsyncMock(return_value=SimpleNamespace(chat_id=123,message_id=7))
 u=SimpleNamespace(effective_chat=SimpleNamespace(id=123),effective_user=SimpleNamespace(id=123),effective_message=SimpleNamespace(message_thread_id=None,reply_text=mock))
 try:
  await g.deliver(u,'**Hola** [Web](https://example.com)','sid','default')
  mock.assert_awaited_once_with('<b>Hola</b> <a href="https://example.com">Web</a>',parse_mode='HTML')
 finally:await g.store.close();await g.hermes.close()

@pytest.mark.parametrize('uri',[
 'obsidian://open?vault=A&file=B<script>',
 'obsidian://open?vault=A&file=B\tC',
 'obsidian://open?vault=A&file=B%0AC',
 'obsidian://open?vault=A&file=%20',
])
def test_unescaped_html_and_controls_rejected(uri):
 assert not valid_obsidian_uri(uri)


def test_unescaped_html_not_extracted_as_shorter_valid_uri():
 text='obsidian://open?vault=A&file=B<script>alert(1)</script>'
 assert extract(text)=={'text':text,'buttons':[]}


def test_closed_parameters_and_incomplete_markdown_unchanged():
 for text in ['[Abrir en Obsidian](obsidian://open?vault=A)',
              '[Abrir en Obsidian](obsidian://open?vault=A&file=...)',
              '[Abrir en Obsidian](javascript:alert(1))']:
  assert extract(text)=={'text':text,'buttons':[]}


def test_reserved_characters_and_percent_case_preserved():
 uri='obsidian://open?vault=A%20B&file=a%2fb%26c%3Fd%23e%25f'
 assert extract(uri)['buttons'][0]['url']==uri


def test_code_and_prose_separated():
 text=f'```\n{URI}\n```\n[{LABEL}]({URI})'
 assert extract(text)=={'text':f'```\n{URI}\n```\n','buttons':[{'text':LABEL,'url':URI}]}


def test_https_bridge_roundtrip():
 from urllib.parse import urlsplit,unquote
 from app.obsidian import obsidian_button_url
 base='https://example.github.io/hermes/bridge/'
 result=obsidian_button_url(URI,base)
 parsed=urlsplit(result)
 assert parsed.query=='';assert unquote(parsed.fragment)==URI
 assert '%2520' in parsed.fragment and '+' not in result
 assert obsidian_button_url(URI)==URI

@pytest.mark.parametrize('base',['http://example.com','https://localhost','https://127.0.0.1','https://example.com/?q=x','https://example.com/#x','https://user:password@example.com/'])
def test_invalid_bridge_config(base):
 from app.obsidian import obsidian_button_url
 with pytest.raises(ValueError):obsidian_button_url(URI,base)

@pytest.mark.asyncio
async def test_delivery_uses_bridge_with_original_fragment(tmp_path):
 from urllib.parse import unquote,urlsplit
 g=Gateway(Config('fake',123,obsidian_bridge_url='https://example.github.io/hermes/bridge/'))
 g.store=await Storage().open(tmp_path/'s.db')
 mock=AsyncMock(return_value=SimpleNamespace(chat_id=123,message_id=7))
 u=SimpleNamespace(effective_chat=SimpleNamespace(id=123),effective_user=SimpleNamespace(id=123),effective_message=SimpleNamespace(message_thread_id=None,reply_text=mock))
 try:
  await g.deliver(u,f'Nota: [{LABEL}]({URI})','sid','default')
  button=mock.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
  assert button.url.startswith('https://');assert button.text==LABEL
  assert unquote(urlsplit(button.url).fragment)==URI
  assert mock.call_args.args[0]=='Nota: '
 finally:await g.store.close();await g.hermes.close()

@pytest.mark.parametrize('markdown',[False,True])
def test_form_encoded_spaces_compatibility(markdown):
 legacy='obsidian://open?vault=My+Vault&file=Inbox%2FPlans+for+today'
 expected='obsidian://open?vault=My%20Vault&file=Inbox%2FPlans%20for%20today'
 source=f'[{LABEL}]({legacy})' if markdown else legacy
 result=extract(source)
 assert result['buttons']==[{'text':LABEL,'url':expected}]
 assert result['text']=='';assert result['normalized_form_spaces']
 assert valid_obsidian_uri(expected)


def test_form_spaces_preserve_real_plus_and_all_other_encoded_bytes():
 legacy='obsidian://open?vault=A+B&file=Inbox%2fC%2B%2B+%E7%AC%94%E8%AE%B0'
 result=extract(legacy)
 assert result['buttons'][0]['url']=='obsidian://open?vault=A%20B&file=Inbox%2fC%2B%2B%20%E7%AC%94%E8%AE%B0'


def test_form_equivalent_duplicates_and_code_protection():
 legacy='obsidian://open?vault=A&file=Plans+today'
 canonical=legacy.replace('+','%20')
 result=extract(legacy+'\n'+canonical+'\n`'+legacy+'`')
 assert len(result['buttons'])==1
 assert result['text']=='\n\n`'+legacy+'`'

@pytest.mark.parametrize('legacy',[
 'obsidian://open?vault=A&file=+',
 'obsidian://open?vault=A&file=Notes+today&unexpected=B',
 'obsidian://open?vault=A&file=%3Cscript%3E+today',
 'obsidian://open?vault=A&file=Notes+...',
])
def test_form_compatibility_keeps_security_policy(legacy):
 assert extract(legacy)=={'text':legacy,'buttons':[]}

@pytest.mark.asyncio
async def test_legacy_real_response_generates_https_button(tmp_path,caplog):
 from urllib.parse import unquote,urlsplit
 g=Gateway(Config('fake',123,obsidian_bridge_url='https://example.github.io/hermes/'))
 g.store=await Storage().open(tmp_path/'s.db')
 mock=AsyncMock(return_value=SimpleNamespace(chat_id=123,message_id=7))
 u=SimpleNamespace(effective_chat=SimpleNamespace(id=123),effective_user=SimpleNamespace(id=123),effective_message=SimpleNamespace(message_thread_id=None,reply_text=mock))
 legacy='obsidian://open?vault=Vault&file=Inbox%2FPlans+for+today'
 try:
  with caplog.at_level(logging.INFO):await g.deliver(u,'Actualicé la nota.\n\n'+legacy,'sid','default')
  button=mock.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
  assert button.text==LABEL
  assert unquote(urlsplit(button.url).fragment)==legacy.replace('+','%20')
  assert mock.call_args.args[0]=='Actualicé la nota.\n\n'
  assert 'form_encoded_spaces' in caplog.text;assert legacy not in caplog.text
 finally:await g.store.close();await g.hermes.close()

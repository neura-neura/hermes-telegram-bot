from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import pytest
from telegram.error import TimedOut,NetworkError,BadRequest,RetryAfter
from app.media import download,DownloadUnavailable,MAX_DOWNLOAD

PAYLOAD=b'original-file-bytes'

def message():
 return SimpleNamespace(message_id=12,photo=[],document=None,audio=None,video=None,voice=SimpleNamespace(file_id='private-id',file_name=None,file_size=len(PAYLOAD),mime_type='audio/ogg'))

def file_object(writer):
 return SimpleNamespace(file_size=len(PAYLOAD),download_to_drive=AsyncMock(side_effect=writer))

@pytest.fixture
def no_wait(monkeypatch):
 sleep=AsyncMock();monkeypatch.setattr('app.media.asyncio.sleep',sleep);return sleep

@pytest.mark.asyncio
async def test_get_file_timeout_refreshes_then_succeeds(tmp_path,no_wait,caplog):
 async def write(path,**kwargs):path.write_bytes(PAYLOAD)
 f=file_object(write);bot=SimpleNamespace(get_file=AsyncMock(side_effect=[TimedOut(),f]))
 att=await download(bot,message(),tmp_path)
 assert att.path.read_bytes()==PAYLOAD;assert att.mime=='audio/ogg'
 assert bot.get_file.await_count==2;assert f.download_to_drive.await_count==1
 assert bot.get_file.call_args.kwargs['read_timeout']==45
 assert f.download_to_drive.call_args.kwargs['read_timeout']==45
 assert list(tmp_path.iterdir())==[att.path]
 assert 'private-id' not in caplog.text

@pytest.mark.asyncio
async def test_partial_download_retry_is_clean_and_refreshes_file(tmp_path,no_wait):
 async def failed(path,**kwargs):
  path.write_bytes(b'partial');raise NetworkError('private CDN URL')
 async def success(path,**kwargs):
  assert not path.exists();path.write_bytes(PAYLOAD)
 first=file_object(failed);second=file_object(success)
 bot=SimpleNamespace(get_file=AsyncMock(side_effect=[first,second]))
 att=await download(bot,message(),tmp_path)
 assert att.path.read_bytes()==PAYLOAD
 assert first.download_to_drive.await_count==second.download_to_drive.await_count==1
 assert bot.get_file.await_count==2

@pytest.mark.asyncio
async def test_truncated_file_is_retried(tmp_path,no_wait):
 calls=0
 async def write(path,**kwargs):
  nonlocal calls
  calls+=1;path.write_bytes(b'x' if calls==1 else PAYLOAD)
 bot=SimpleNamespace(get_file=AsyncMock(return_value=file_object(write)))
 att=await download(bot,message(),tmp_path)
 assert calls==2;assert att.path.read_bytes()==PAYLOAD

@pytest.mark.asyncio
async def test_exhausted_download_has_safe_error_and_no_partial(tmp_path,no_wait):
 async def failed(path,**kwargs):path.write_bytes(b'partial');raise TimedOut()
 bot=SimpleNamespace(get_file=AsyncMock(return_value=file_object(failed)))
 with pytest.raises(DownloadUnavailable,match='No se envió ninguna tarea a Hermes'):
  await download(bot,message(),tmp_path)
 assert bot.get_file.await_count==3;assert list(tmp_path.iterdir())==[]

@pytest.mark.asyncio
async def test_permanent_error_is_not_retried(tmp_path,no_wait):
 bot=SimpleNamespace(get_file=AsyncMock(side_effect=BadRequest('invalid file_id')))
 with pytest.raises(DownloadUnavailable):await download(bot,message(),tmp_path)
 assert bot.get_file.await_count==1;no_wait.assert_not_awaited()

@pytest.mark.asyncio
async def test_size_limit_is_not_retried(tmp_path,no_wait):
 m=message();m.voice.file_size=MAX_DOWNLOAD+1
 bot=SimpleNamespace(get_file=AsyncMock())
 with pytest.raises(ValueError,match='20 MB'):await download(bot,m,tmp_path)
 bot.get_file.assert_not_awaited()

@pytest.mark.asyncio
async def test_rate_limit_wait_is_honored(tmp_path,no_wait):
 async def write(path,**kwargs):path.write_bytes(PAYLOAD)
 bot=SimpleNamespace(get_file=AsyncMock(side_effect=[RetryAfter(3),file_object(write)]))
 assert (await download(bot,message(),tmp_path)).path.read_bytes()==PAYLOAD
 no_wait.assert_awaited_once_with(3)

@pytest.mark.asyncio
async def test_cancel_cleans_partial_without_retry(tmp_path,no_wait):
 async def cancel(path,**kwargs):path.write_bytes(b'partial');raise asyncio.CancelledError()
 bot=SimpleNamespace(get_file=AsyncMock(return_value=file_object(cancel)))
 with pytest.raises(asyncio.CancelledError):await download(bot,message(),tmp_path)
 assert list(tmp_path.iterdir())==[];assert bot.get_file.await_count==1

@pytest.mark.asyncio
async def test_media_pipeline_does_not_repeat_hermes_after_read_retry(tmp_path,no_wait):
 from app.bot import Gateway
 from app.config import Config
 from app.storage import Storage
 g=Gateway(Config('fake',123));g.store=await Storage().open(tmp_path/'state.db')
 async def write(path,**kwargs):path.write_bytes(PAYLOAD)
 g.application=SimpleNamespace(bot=SimpleNamespace(get_file=AsyncMock(side_effect=[TimedOut(),file_object(write)])))
 g.say=AsyncMock();g.transcriber.transcribe=AsyncMock(return_value='Añade una tarea')
 g.converse=AsyncMock()
 m=message();m.caption=None;m.message_thread_id=None
 u=SimpleNamespace(effective_message=m,effective_chat=SimpleNamespace(id=123),effective_user=SimpleNamespace(id=123))
 try:
  await g.process_media([u])
  g.transcriber.transcribe.assert_awaited_once();g.converse.assert_awaited_once()
  assert g.application.bot.get_file.await_count==2
 finally:await g.store.close();await g.hermes.close()

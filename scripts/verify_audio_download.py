"""Real Telegram file read + local STT, with one injected pre-read timeout.

Sends a synthetic diagnostic voice note to OWNER; never executes a Hermes turn.
"""
import asyncio,hashlib,json,tempfile
from pathlib import Path
from types import SimpleNamespace
from telegram import Bot
from telegram.error import TimedOut
from app.config import Config,ROOT
from app.media import download,Transcriber
from app.hermes import HermesClient
from scripts.audio_smoke import command

async def main():
 c=Config.load();h=HermesClient(c);t=Transcriber(c,h)
 try:
  with tempfile.TemporaryDirectory(dir=ROOT/'data/tmp') as td:
   td=Path(td);src=td/'speech.aiff';ogg=td/'speech.ogg'
   await command('/usr/bin/say','-v','Paulina','-o',str(src),'Esta es una prueba de descarga y transcripción de audio.')
   await command('/opt/homebrew/bin/ffmpeg','-v','error','-y','-i',str(src),'-c:a','libopus',str(ogg))
   async with Bot(c.token) as bot:
    with ogg.open('rb') as f:
     message=await bot.send_voice(c.owner,f,caption='Prueba técnica de recuperación de audio. Este envío no ejecuta instrucciones ni modifica notas.',read_timeout=45,write_timeout=30)
    calls=0
    async def get_file(file_id,**kwargs):
     nonlocal calls
     calls+=1
     if calls==1:raise TimedOut()
     return await bot.get_file(file_id,**kwargs)
    incoming=await download(SimpleNamespace(get_file=get_file),message,td)
    assert calls==2
    assert hashlib.sha256(incoming.path.read_bytes()).digest()==hashlib.sha256(ogg.read_bytes()).digest()
    transcript=await t.transcribe(incoming)
    assert 'prueba' in transcript.lower() and 'audio' in transcript.lower()
    # A normal subsequent download must need only one getFile read.
    subsequent=await download(bot,message,td)
    assert subsequent.path.read_bytes()==ogg.read_bytes()
    result={'status':'PASS','transport':'real Bot API voice upload/getFile/download','transient_failure':'one injected TimedOut before getFile','automatic_recovery':True,'bytes_verified':True,'local_transcription':True,'normal_download':True,'hermes_turns_executed':0}
    (ROOT/'docs/audio-download-validation.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
 finally:await h.close()

if __name__=='__main__':asyncio.run(main())

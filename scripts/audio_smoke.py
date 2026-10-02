import asyncio,json,tempfile,wave,time
from pathlib import Path
from app.config import ROOT,Config
from app.hermes import HermesClient
from app.media import Transcriber,Attachment
from app.routing import intent
async def command(*args):
 p=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
 await p.wait()
 if p.returncode:raise RuntimeError('Audio synthesis/conversion failed')
async def main():
 c=Config.load();h=HermesClient(c);tr=Transcriber(c,h);result={}
 try:
  await tr.ready()
  with tempfile.TemporaryDirectory(dir=ROOT/'data/tmp') as directory:
   directory=Path(directory)
   for lang,voice,text in [('es','Paulina','Muéstrame mis bots.'),('en','Samantha','Explain what a web socket is.'),('zh','Tingting','请解释什么是人工智能。')]:
    src=directory/(lang+'.aiff');ogg=directory/(lang+'.ogg')
    await command('/usr/bin/say','-v',voice,'-o',str(src),text)
    await command('/opt/homebrew/bin/ffmpeg','-v','error','-y','-i',str(src),'-c:a','libopus',str(ogg))
    a=Attachment(ogg,ogg.name,'audio/ogg',ogg.stat().st_size)
    transcript=await tr.transcribe(a)
    result[lang]={'transcript':transcript,'route':intent(transcript).action,'nonempty':bool(transcript)}
    print(lang,json.dumps(result[lang],ensure_ascii=False),flush=True)
    if lang=='es':
     try:
      native=await h.transcribe(a);result['native_hermes']={'transcript':native,'nonempty':bool(native)}
      print('native_hermes',bool(native),flush=True)
     except Exception as e:result['native_hermes']={'error':type(e).__name__}
   silence=directory/'silence.wav'
   with wave.open(str(silence),'w') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0'*16000*2*3)
   answer=await tr.transcribe(Attachment(silence,'silence.wav','audio/wav',silence.stat().st_size))
   result['silence']={'empty':not answer};print('silence',not answer,flush=True)
 finally:await h.close()
 (ROOT/'docs/audio-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())

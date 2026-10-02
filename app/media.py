import asyncio, mimetypes, re, tempfile, time, logging
from dataclasses import dataclass
from pathlib import Path
from app.config import ROOT
log=logging.getLogger(__name__)
MAX_DOWNLOAD=20*1024*1024
@dataclass
class Attachment:
    path: Path
    filename: str
    mime: str
    size: int
    source: str='telegram'
    @property
    def image(self):return self.mime.startswith('image/')
    @property
    def audio(self):return self.mime.startswith('audio/')

def mime_type(name, declared=None):
    guessed=mimetypes.guess_type(name)[0]
    if guessed and guessed.startswith(('image/','audio/')):return guessed
    return declared or guessed or ('text/plain' if Path(name).suffix.lower() in ('.py','.js','.ts','.go','.rs','.c','.cpp','.h','.sh','.yaml','.yml','.md') else 'application/octet-stream')

def safe_name(name):
    return (re.sub(r'[^\w. -]','_',Path(name.replace('\\','/')).name)[:180] or 'attachment.bin')

async def download(bot, message, directory):
    source=message.photo[-1] if message.photo else (message.document or message.voice or message.audio or message.video)
    if not source:return None
    if source.file_size and source.file_size>MAX_DOWNLOAD:raise ValueError('Telegram permite descargar hasta 20 MB por archivo.')
    name=getattr(source,'file_name',None) or ('photo.jpg' if message.photo else 'voice.ogg' if message.voice else 'audio.mp3' if message.audio else 'video.mp4')
    name=safe_name(name);path=directory/(str(message.message_id)+'_'+name)
    f=await bot.get_file(source.file_id)
    await f.download_to_drive(path)
    size=(await asyncio.to_thread(path.stat)).st_size
    if size>MAX_DOWNLOAD:raise ValueError('Archivo mayor de 20 MB')
    mime=mime_type(name,getattr(source,'mime_type',None))
    log.info('file received type=%s bytes=%d',mime,size)
    return Attachment(path,name,mime,size)

class Transcriber:
    def __init__(self,config,hermes):
        self.config=config;self.hermes=hermes;self.model=None;self.lock=asyncio.Lock()
    def _load(self):
        from faster_whisper import WhisperModel
        self.model=WhisperModel(self.config.model,device='cpu',compute_type='int8',cpu_threads=4,
            download_root=str(ROOT/'data/models'))
    async def ready(self):
        if self.config.engine=='hermes-local':
            c=await self.hermes.request('GET','/api/transcribe/capability')
            return c.get('available') and c.get('provider') in ('local','local_command')
        async with self.lock:
            if self.model is None:await asyncio.to_thread(self._load)
        return True
    async def normalize(self, path):
        wav=path.with_name(path.stem+'.normalized.wav')
        proc=await asyncio.create_subprocess_exec('/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y',
            '-i',str(path),'-ac','1','-ar','16000',str(wav),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.wait(),120)
        except BaseException:
            proc.kill();await proc.wait();wav.unlink(missing_ok=True);raise
        if proc.returncode:raise ValueError('Audio inválido o formato no decodificable')
        import wave
        def duration():
            with wave.open(str(wav)) as f:return f.getnframes()/f.getframerate()
        seconds=await asyncio.to_thread(duration)
        if seconds>self.config.max_audio:raise ValueError('Audio supera la duración configurada')
        return wav
    def _transcribe(self, wav):
        segments,info=self.model.transcribe(str(wav),language=None if self.config.language=='auto' else self.config.language,
            beam_size=5,vad_filter=True,condition_on_previous_text=False,
            initial_prompt='Hermes, Telegram, bots, perfiles, chats, Little K.')
        parts=[s.text.strip() for s in segments if s.no_speech_prob<0.65 and s.avg_logprob>-1.0]
        return ' '.join(parts),info.language
    async def transcribe(self, att):
        started=time.monotonic();log.info('transcription start bytes=%d',att.size)
        if self.config.engine=='hermes-local':return await self.hermes.transcribe(att)
        wav=await self.normalize(att.path)
        try:
            async with self.lock:
                if self.model is None:await asyncio.to_thread(self._load)
                text,language=await asyncio.to_thread(self._transcribe,wav)
            log.info('transcription end seconds=%.2f language=%s',time.monotonic()-started,language)
            return text
        finally:await asyncio.to_thread(wav.unlink,missing_ok=True)

class MediaGroups:
    """Debounce album pieces; one task/turn for each Telegram media_group_id."""
    def __init__(self, delay=1.2):self.delay=delay;self.groups={};self.tasks={}
    def add(self,key,item,flush):
        self.groups.setdefault(key,[]).append(item)
        if key in self.tasks:self.tasks[key].cancel()
        async def collect():
            await asyncio.sleep(self.delay)
            items=self.groups.pop(key);self.tasks.pop(key,None)
            await flush(sorted(items,key=lambda u:u.effective_message.message_id))
        self.tasks[key]=asyncio.create_task(collect())
    async def close(self):
        tasks=list(self.tasks.values())
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

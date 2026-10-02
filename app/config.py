import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parent.parent

@dataclass
class Config:
    token: str = field(repr=False)
    owner: int
    base_url: str = 'http://127.0.0.1:8787'
    webui_env: Path = Path.home()/'repos/hermes-webui/.env'
    users: frozenset = frozenset()
    chats: frozenset = frozenset()
    engine: str = 'faster-whisper'
    model: str = 'medium'
    language: str = 'auto'
    max_audio: int = 7200
    obsidian_bridge_url: str = ''
    @classmethod
    def load(cls):
        d = {**dotenv_values(ROOT/'.env'), **os.environ}
        url = d.get('HERMES_BASE_URL', 'http://127.0.0.1:8787').rstrip('/')
        if urlparse(url).hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('Hermes must use a loopback address')
        parse = lambda s: frozenset(int(x) for x in s.split(',') if x.strip())
        c = cls(d['TELEGRAM_BOT_TOKEN'], int(d['OWNER_USER_ID']), url,
            Path(d.get('HERMES_WEBUI_ENV',str(Path.home()/'repos/hermes-webui/.env'))).expanduser(),
            parse(d.get('ALLOWED_USER_IDS','')), parse(d.get('ALLOWED_CHAT_IDS','')),
            d.get('TRANSCRIPTION_ENGINE','faster-whisper'), d.get('TRANSCRIPTION_MODEL','medium'),
            d.get('TRANSCRIPTION_LANGUAGE','auto'), int(d.get('MAX_AUDIO_SECONDS',7200)), d.get('OBSIDIAN_BRIDGE_URL','').strip())
        if c.owner <= 0 or c.engine not in ('faster-whisper','hermes-local'):
            raise ValueError('Invalid owner or transcription engine')
        if c.obsidian_bridge_url:
            from app.obsidian import obsidian_button_url
            obsidian_button_url('obsidian://open?vault=test&file=test',c.obsidian_bridge_url)
        return c
    def allowed(self, user, chat, private):
        if user is None: return False
        return (user == self.owner or user in self.users) and (private or chat in self.chats)
    def admin(self, user): return user == self.owner

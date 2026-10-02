"""Adapter to the installed Hermes Web UI API (same sessions, tools and attachments)."""
import asyncio, json, re, mimetypes
from pathlib import Path
from urllib.parse import quote
import httpx
from dotenv import dotenv_values

class BackendError(Exception): pass

class HermesClient:
    def __init__(self, config):
        self.config=config
        self.http=httpx.AsyncClient(base_url=config.base_url,follow_redirects=True,
            timeout=httpx.Timeout(600,connect=10),trust_env=False)
        self.auth_lock=asyncio.Lock()
        self.authenticated=False
        self.profile_cookies={}
        from app.native import NativeSessions
        self.native=NativeSessions()
    async def authenticate(self, force=False):
        async with self.auth_lock:
            if self.authenticated and not force:return
            password=await asyncio.to_thread(lambda: dotenv_values(self.config.webui_env).get('HERMES_WEBUI_PASSWORD'))
            if password:
                r=await self.http.post('/api/auth/login',json={'password':password})
                if r.status_code!=200:raise BackendError('No se pudo autenticar con Hermes Web UI')
            shell=await self.http.get('/')
            m=re.search(r'csrfToken:("[^"\n]*")',shell.text)
            if m:self.http.headers['X-Hermes-CSRF-Token']=json.loads(m[1])
            self.profile_cookies.clear()
            self.authenticated=True
    async def prepare_profile(self, profile):
        await self.authenticate()
        async with self.auth_lock:
            if profile in self.profile_cookies:return
            cookies='; '.join(f'{k}={v}' for k,v in self.http.cookies.items() if k!='hermes_profile')
            r=await self.http.post('/api/profile/switch',json={'name':profile},headers={'Cookie':cookies})
            if r.status_code!=200:raise BackendError(f'No se pudo activar el perfil {profile}')
            value=r.cookies.get('hermes_profile')
            if not value:raise BackendError('Hermes no entregó una cookie de perfil')
            self.profile_cookies[profile]=value
    def headers(self, profile):
        cookies='; '.join(f'{k}={v}' for k,v in self.http.cookies.items() if k!='hermes_profile')
        value=self.profile_cookies.get(profile)
        if value:cookies+='; hermes_profile='+value
        return {'Cookie':cookies}
    async def request(self, method, path, profile='default', **kwargs):
        for attempt in range(4):
            try:
                await self.prepare_profile(profile)
                r=await self.http.request(method,path,headers=self.headers(profile),**kwargs)
                if r.status_code==401:
                    await self.authenticate(force=True)
                    await self.prepare_profile(profile)
                    r=await self.http.request(method,path,headers=self.headers(profile),**kwargs)
                if method=='GET' and r.status_code in (429,502,503,504) and attempt<3:
                    await asyncio.sleep(2**attempt);continue
                if r.status_code>=400:
                    try: code=r.json().get('code','')
                    except ValueError: code=''
                    raise BackendError(f'Hermes respondió HTTP {r.status_code}'+(f' ({code})' if code else ''))
                return r.json()
            except (httpx.ConnectError,httpx.ConnectTimeout):
                # Connection failure is safe to retry. Never replay an ambiguous turn.
                if attempt==3:raise BackendError('Hermes no está disponible; revisa /status') from None
                await asyncio.sleep(2**attempt)
    async def health(self):return await self.request('GET','/health')
    async def profiles(self):return (await self.request('GET','/api/profiles'))['profiles']
    async def bots(self):
        # Desktop Bot Mode roster is made from live Hermes profiles, distinct from
        # the gateway/UI profile. Friendly names are metadata, never identity.
        profiles=await self.profiles()
        def enrich(rows):
            import yaml
            for row in rows:
                meta=Path(row['path'])/'profile.yaml'
                data=yaml.safe_load(meta.read_text()) if meta.exists() else {}
                row['label']=(data or {}).get('display_name') or row['name']
            return rows
        return await asyncio.to_thread(enrich,profiles)
    async def bot_chat(self, bot_profile):return await self.native.canonical(bot_profile)
    async def personalities(self, profile):return (await self.request('GET','/api/personalities',profile)).get('personalities',[])
    async def chats(self, profile='default', search=None):
        path='/api/sessions/search' if search else '/api/sessions'
        params={'q':search,'content':'1','depth':'0','all_profiles':'1'} if search else {'all_profiles':'1'}
        return (await self.request('GET',path,profile,params=params)).get('sessions',[])
    async def chat(self, sid, profile):
        if sid in self.native.sessions:return await self.native.chat(sid,profile)
        return (await self.request('GET','/api/session',profile,params={'session_id':sid}))['session']
    async def create(self, profile='default', personality=None):
        s=(await self.request('POST','/api/session/new',profile,json={'profile':profile,'worktree':False}))['session']
        if personality:await self.request('POST','/api/personality/set',profile,json={'session_id':s['session_id'],'name':personality})
        return s
    async def upload(self, sid, profile, attachment):
        if sid in self.native.sessions:return await self.native.upload(sid,profile,attachment)
        data=await asyncio.to_thread(attachment.path.read_bytes)
        return await self.request('POST','/api/upload',profile,data={'session_id':sid},
            files={'file':(attachment.filename,data,attachment.mime)})
    async def models(self, profile):
        d=await self.request('GET','/api/models',profile)
        return [dict(m,provider=g.get('provider_id',g['provider'])) for g in d.get('groups',[]) for m in g.get('models',[])]
    async def tools(self, profile):
        # Reuse native API inventory rather than guessing the WebUI tools route.
        keyfile=Path.home()/'.hermes'/('.env' if profile=='default' else f'profiles/{profile}/.env')
        key=await asyncio.to_thread(lambda:dotenv_values(keyfile).get('API_SERVER_KEY'))
        native=[]
        if key:
            async with httpx.AsyncClient(timeout=20,trust_env=False) as c:
                r=await c.get('http://127.0.0.1:8642'+('/p/'+quote(profile) if profile!='default' else '')+'/v1/toolsets',headers={'Authorization':'Bearer '+key})
                if r.status_code==200:
                    d=r.json();native=d.get('data',d.get('toolsets',[]))
        mcp=(await self.request('GET','/api/mcp/tools',profile)).get('tools',[])
        return {'toolsets':native,'mcp':mcp}
    async def transcribe(self, attachment):
        capability=await self.request('GET','/api/transcribe/capability')
        if capability.get('provider') not in ('local','local_command'):
            raise BackendError('Hermes no ofrece transcripción local; selecciona faster-whisper')
        data=await asyncio.to_thread(attachment.path.read_bytes)
        r=await self.request('POST','/api/transcribe',files={'file':(attachment.filename,data,attachment.mime)})
        return r.get('transcript','')
    async def start(self, sid, profile, message=None, attachments=None, model=None, regen=False):
        if sid in self.native.sessions:
            if regen:raise BackendError('La API nativa no expone regeneración del Bot Chat')
            descriptor=await self.native.start(sid,profile,message,attachments)
            return {'stream_id':descriptor}
        body={'session_id':sid}
        if regen:
            s=await self.chat(sid,profile)
            revision=s.get('regeneration_revision')
            body.update(regenerate=True,regeneration_revision=revision)
        else:
            if attachments:
                # WebUI's composer embeds uploaded absolute paths in the prompt;
                # the attachment objects alone only embed native images.
                paths=[a['path'] for a in attachments if a.get('path')]
                message=(message or '')+'\n\n[Attached files: '+', '.join(paths)+']'
            body.update(message=message,attachments=attachments or [])
            if model:body.update(model=model['id'],model_provider=model['provider'],explicit_model_pick=True)
        return await self.request('POST','/api/chat/start',profile,json=body)
    async def events(self, stream_id, profile):
        if isinstance(stream_id,dict) and stream_id.get('native'):
            async for event,payload in self.native.events(stream_id):yield event,payload
            return
        await self.prepare_profile(profile)
        cursor=None
        for attempt in range(4):
            event='message';data=[]
            try:
                params={'stream_id':stream_id,'replay':'1'}
                if cursor:params['after_event_id']=cursor
                async with self.http.stream('GET','/api/chat/stream',params=params,headers=self.headers(profile)) as r:
                    if r.status_code!=200:raise BackendError(f'Stream Hermes HTTP {r.status_code}')
                    async for line in r.aiter_lines():
                        if line.startswith('event:'):event=line[6:].strip()
                        elif line.startswith('id:'):cursor=line[3:].strip()
                        elif line.startswith('data:'):data.append(line[5:].lstrip())
                        elif not line and data:
                            try:payload=json.loads('\n'.join(data))
                            except ValueError:payload={'text':'\n'.join(data)}
                            data=[]
                            yield event,payload
                            if event in ('done','apperror','stream_end','cancel','error'):return
                            event='message'
                raise httpx.ReadError('Stream disconnected')
            except (httpx.ReadError,httpx.ReadTimeout,httpx.ConnectError):
                if attempt==3:raise BackendError('Streaming interrumpido; consulta el chat antes de reenviar') from None
                await asyncio.sleep(2**attempt)
    async def mutate(self, action, sid, profile, **extra):
        if sid in self.native.sessions:return await self.native.mutate(action,sid,profile,extra)
        return await self.request('POST','/api/session/'+action,profile,json={'session_id':sid,**extra})
    async def download(self, path, sid, profile):
        if sid in self.native.sessions:return await self.native.download(path,profile)
        await self.prepare_profile(profile)
        limit=50*1024*1024
        async with self.http.stream('GET','/api/file/raw',params={'path':path,'session_id':sid},headers=self.headers(profile)) as r:
            if r.status_code!=200:raise BackendError(f'Archivo no disponible (HTTP {r.status_code})')
            if int(r.headers.get('content-length','0'))>limit:raise BackendError('El archivo supera 50 MB')
            chunks=[];size=0
            async for chunk in r.aiter_bytes():
                size+=len(chunk)
                if size>limit:raise BackendError('El archivo supera 50 MB')
                chunks.append(chunk)
            data=b''.join(chunks)
            mime=r.headers.get('content-type','application/octet-stream').split(';')[0]
        if mime=='application/octet-stream':mime=mimetypes.guess_type(path)[0] or mime
        if data.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
        elif data.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
        return data,mime
    async def close(self):await self.http.aclose();await self.native.close()

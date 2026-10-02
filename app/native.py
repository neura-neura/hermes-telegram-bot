"""Native Hermes session API for Desktop canonical Bot Chats."""
import asyncio,base64,json,mimetypes,secrets
from pathlib import Path
from urllib.parse import quote
import httpx
from dotenv import dotenv_values
from app.hermes import BackendError

class NativeSessions:
    def __init__(self):
        self.http=httpx.AsyncClient(timeout=httpx.Timeout(600,connect=10),trust_env=False)
        self.sessions=set()
    def home(self,profile):return Path.home()/'.hermes' if profile=='default' else Path.home()/'.hermes/profiles'/profile
    async def auth(self,profile):
        key=await asyncio.to_thread(lambda:dotenv_values(self.home(profile)/'.env').get('API_SERVER_KEY'))
        if not key:raise BackendError('Falta la clave de la API nativa del perfil')
        url='http://127.0.0.1:8642'+('' if profile=='default' else '/p/'+quote(profile))
        return url,{'Authorization':'Bearer '+key}
    async def request(self,method,path,profile,**kwargs):
        url,headers=await self.auth(profile)
        r=await self.http.request(method,url+path,headers=headers,**kwargs)
        if r.status_code>=400:raise BackendError(f'API nativa Hermes HTTP {r.status_code}')
        return r.json()
    async def canonical(self,profile):
        d=await self.request('GET','/api/sessions',profile,params={'title':'Bot Chat','include_hidden':'true'})
        if d.get('data'):sid=d['data'][0]['id']
        else:
            d=await self.request('POST','/api/sessions',profile,json={'title':'Bot Chat','source':'api_server'});sid=d['session']['id']
        self.sessions.add(sid)
        return await self.chat(sid,profile)
    async def chat(self,sid,profile):
        d=(await self.request('GET','/api/sessions/'+quote(sid),profile))['session']
        msgs=(await self.request('GET','/api/sessions/'+quote(sid)+'/messages',profile,params={'limit':200,'order':'latest'})).get('data',[])
        # Native latest pages return chronological order within the latest window.
        d.update(session_id=sid,profile=profile,messages=msgs)
        return d
    async def upload(self,sid,profile,attachment):
        # Native chat supports text/images, not document multipart. On this LOCAL
        # install preserve original files in Hermes' inbox and pass their paths to
        # Hermes tools, the same local-file mechanism used by its CLI.
        root=self.home(profile)/'uploads/telegram'/sid
        def copy():
            root.mkdir(parents=True,exist_ok=True,mode=0o700)
            dest=root/(secrets.token_hex(5)+'_'+attachment.filename)
            with dest.open('xb') as f:f.write(attachment.path.read_bytes())
            dest.chmod(0o600)
            return {'filename':attachment.filename,'path':str(dest),'mime':attachment.mime,'size':attachment.size,'is_image':attachment.image}
        return await asyncio.to_thread(copy)
    async def start(self,sid,profile,message,attachments):
        refs=attachments or []
        paths=[r['path'] for r in refs]
        text=message or ''
        if paths:text+='\n\n[Attached files: '+', '.join(paths)+']'
        content=[{'type':'text','text':text}]
        for r in refs:
            if r.get('is_image'):
                data=await asyncio.to_thread(Path(r['path']).read_bytes)
                content.append({'type':'image_url','image_url':{'url':'data:'+r['mime']+';base64,'+base64.b64encode(data).decode()}})
        return {'native':True,'sid':sid,'profile':profile,'body':{'message':content if len(content)>1 else text}}
    async def events(self,descriptor):
        sid=descriptor['sid'];profile=descriptor['profile'];url,headers=await self.auth(profile)
        event='message';data=[];final=None
        async with self.http.stream('POST',url+'/api/sessions/'+quote(sid)+'/chat/stream',headers=headers,json=descriptor['body']) as r:
            if r.status_code!=200:raise BackendError(f'Stream nativo Hermes HTTP {r.status_code}')
            async for line in r.aiter_lines():
                if line.startswith('event:'):event=line[6:].strip()
                elif line.startswith('data:'):data.append(line[5:].lstrip())
                elif not line and data:
                    payload=json.loads('\n'.join(data));data=[]
                    if payload.get('run_id'):descriptor['run_id']=payload['run_id']
                    if event=='assistant.delta':yield 'token',{'text':payload.get('delta','')}
                    elif event in ('tool.started','tool.completed'):yield 'tool',{'name':payload.get('tool_name'),'event_type':event}
                    elif event=='assistant.completed':final=payload
                    elif event=='approval.request':yield 'approval',dict(payload,native=True)
                    elif event=='error':yield 'error',payload
                    elif event in ('run.failed','run.cancelled'):yield 'error',{'message':'La ejecución nativa no terminó correctamente'}
                    elif event=='run.queued':raise BackendError('Mensaje encolado en el bot vivo. Revisa su chat canónico en Hermes; no reenvíes la tarea.')
                    elif event=='done':
                        snapshot=await self.chat(sid,profile)
                        if final:
                            snapshot['messages'].append({'role':'assistant','content':final.get('content',''),'id':final.get('message_id')})
                        yield 'done',{'session':snapshot};return
                    event='message'
    async def stop(self,descriptor):
        if descriptor.get('run_id'):await self.request('POST','/v1/runs/'+quote(descriptor['run_id'])+'/stop',descriptor['profile'],json={})
    async def mutate(self,action,sid,profile,extra):
        path='/api/sessions/'+quote(sid)
        if action=='branch':
            d=await self.request('POST',path+'/fork',profile,json=extra);new=d['session']['id'];self.sessions.add(new);return {'session_id':new}
        if action=='delete':return await self.request('DELETE',path,profile)
        if action=='archive':extra={'archived':True}
        if action=='rename':extra={'title':extra['title']}
        return await self.request('PATCH',path,profile,json=extra)
    async def download(self,path,profile):
        p=Path(path).expanduser().resolve();roots=[Path.home()/'workspace',self.home(profile)/'workspace',self.home(profile)/'uploads/telegram']
        if not any(p.is_relative_to(root.resolve()) for root in roots):raise BackendError('Salida nativa fuera de los directorios de archivos autorizados')
        if p.name.startswith('.') or p.name in ('config.yaml','profile.yaml') or 'secrets' in p.parts or '.env' in p.name:raise BackendError('Archivo privado bloqueado')
        def read():
            if p.stat().st_size>50*1024*1024:raise BackendError('Archivo mayor de 50 MB')
            return p.read_bytes()
        return await asyncio.to_thread(read),mimetypes.guess_type(str(p))[0] or 'application/octet-stream'
    async def close(self):await self.http.aclose()

import asyncio, contextlib, io, json, logging, math, tempfile, time
from pathlib import Path
from telegram import BotCommand, InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, AIORateLimiter
from telegram.error import BadRequest, TelegramError
from app.config import Config,ROOT
from app.storage import Storage
from app.hermes import HermesClient,BackendError
from app.media import download,Transcriber,MediaGroups,mime_type
from app.formatting import split_text,telegram_html,output_paths
from app.routing import intent,match_name
from app.obsidian import extract_obsidian_telegram_actions,LABEL,obsidian_button_url
log=logging.getLogger(__name__)
COMMANDS={
    'start':'Abrir Hermes','home':'Menú principal','help':'Ayuda','status':'Diagnóstico real',
    'new':'Nuevo chat','chats':'Conversaciones Hermes','chat':'Seleccionar chat',
    'bots':'Agentes y personalidades Hermes','bot':'Seleccionar agente',
    'profiles':'Perfiles Hermes','profile':'Seleccionar perfil','models':'Modelos Hermes',
    'model':'Seleccionar modelo','providers':'Proveedores disponibles','tools':'Tools y MCP',
    'current':'Contexto activo','back':'Chat anterior','search':'Buscar conversaciones',
    'rename':'Renombrar chat','archive':'Archivar chat','delete':'Eliminar con confirmación',
    'regen':'Regenerar respuesta','branch':'Crear rama','settings':'Ajustes reales',
    'refresh':'Actualizar','cancel':'Cancelar petición o menú','attach':'Preparar varios archivos',
    'send':'Enviar archivos preparados','export':'Exportar conversación'}
def session_profile(v):return v.get('bot_profile') or v['profile']

ADMIN={'rename','archive','delete','regen','branch','settings','model','models','providers','profile','bot','tools'}

class Gateway:
    def __init__(self,config):
        self.config=config;self.hermes=HermesClient(config);self.store=Storage()
        self.transcriber=Transcriber(config,self.hermes);self.groups=MediaGroups()
        self.locks={};self.session_locks={};self.running={};self.pending={};self.tasks=set()
    def scope(self,u):
        m=u.effective_message
        return f'{u.effective_chat.id}:{m.message_thread_id or 0}:{u.effective_user.id}'
    def accepted(self,u):
        if not u.effective_user or not u.effective_chat:return False
        if not self.config.allowed(u.effective_user.id,u.effective_chat.id,u.effective_chat.type=='private'):return False
        m=u.effective_message
        if u.effective_chat.type!='private':
            botname=self.application.bot.username
            return bool(u.callback_query or (m.text or '').startswith('/') or
                '@'+botname in (m.text or m.caption or '') or
                (m.reply_to_message and m.reply_to_message.from_user and m.reply_to_message.from_user.id==self.application.bot.id))
        return True
    async def start(self,app):
        self.application=app;await self.store.open();await self.store.cleanup()
        await app.bot.set_my_commands([BotCommand(k,v) for k,v in COMMANDS.items()])
        me=await app.bot.get_me();log.info('Telegram connected bot=@%s owner=%d',me.username,self.config.owner)
    async def close(self,app):
        await self.groups.close()
        tasks=list(self.tasks)
        for t in tasks:t.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.pending.clear()
        await self.hermes.close();await self.store.close()
    async def say(self,u,text,keyboard=None,edit=False):
        if edit and u.callback_query:
            try:
                await u.callback_query.edit_message_text(text,reply_markup=keyboard)
                return u.callback_query.message
            except BadRequest as e:
                if 'not modified' in str(e).lower():return u.callback_query.message
        return await u.effective_message.reply_text(text,reply_markup=keyboard)
    async def buttons(self,scope,rows):
        return Keyboard([[Button(label,callback_data=await self.store.callback(scope,action)) for label,action in row] for row in rows])
    async def active(self,scope,create=False):
        v=await self.store.get(scope)
        if not v.get('sid') and create:
            s=await self.hermes.create(v['profile']);await self.store.activate(scope,s['session_id'],v['profile']);v=await self.store.get(scope)
        if v.get('bot_native') and v.get('sid'):self.hermes.native.sessions.add(v['sid'])
        s=await self.hermes.chat(v['sid'],session_profile(v)) if v.get('sid') else None
        return v,s
    async def current_text(self,scope):
        v,s=await self.active(scope)
        if not s:return 'Hermes\n\n💬 Sin chat activo\n👤 '+v['profile']
        return f"Hermes\n\n💬 {s.get('title') or 'Sin título'}\n🤖 {v.get('bot') or s.get('personality') or s.get('profile') or v['profile']}\n👤 {v['profile']}\n🧠 {s.get('model') or 'Modelo del perfil'}\n🔌 {s.get('model_provider') or 'Proveedor del perfil'}"
    async def home(self,u,edit=False):
        scope=self.scope(u)
        kb=await self.buttons(scope,[[('💬 Chats',{'action':'chats'})],[('🤖 Bots',{'action':'bots'}),('👤 Perfiles',{'action':'profiles'})],
            [('➕ Nuevo chat',{'action':'new'})],[('🧠 Modelos',{'action':'models'}),('🛠 Tools',{'action':'tools'})],
            [('⚙️ Ajustes',{'action':'settings'})],[('🔄 Actualizar',{'action':'home'}),('ℹ️ Estado',{'action':'status'})]])
        await self.say(u,await self.current_text(scope),kb,edit)
    async def listing(self,u,kind,page=0,query='',edit=False):
        scope=self.scope(u);v=await self.store.get(scope);profile=v['profile'];rows=[]
        if kind in ('chats','search'):
            items=await self.hermes.chats(profile,query if kind=='search' else None)
            for item in items:
                rows.append((item.get('title') or item['session_id'],{'action':'select_chat','sid':item['session_id'],'profile':item.get('profile') or 'default'}))
        elif kind in ('profiles','bots'):
            if kind=='profiles':
                profiles=await self.hermes.profiles()
                rows=[('👤 '+p['name'],{'action':'select_profile','profile':p['name']}) for p in profiles]
            else:
                rows=[('🤖 '+p['label'],{'action':'select_bot','profile':p['name'],'name':p['label']}) for p in await self.hermes.bots()]
        elif kind=='models':
            rows=[(m.get('label',m['id'])+' · '+m['provider'],{'action':'select_model','model':{'id':m['id'],'provider':m['provider']}}) for m in await self.hermes.models(profile)]
        count=max(1,math.ceil(len(rows)/7));page=max(0,min(page,count-1))
        kbrows=[[(label[:60],action)] for label,action in rows[page*7:page*7+7]]
        kbrows.append([('◀️',{'action':kind,'page':max(0,page-1),'query':query}),(f'{page+1}/{count}',{'action':kind,'page':page,'query':query}),('▶️',{'action':kind,'page':min(count-1,page+1),'query':query})])
        kbrows.append([('🏠 Inicio',{'action':'home'}),('🔄 Actualizar',{'action':kind,'page':page,'query':query})])
        title={'chats':'💬 Chats','search':'🔎 '+query,'profiles':'👤 Perfiles','bots':'🤖 Bots de Hermes','models':'🧠 Modelos'}[kind]
        if kind=='bots':title+='\nAbre el chat del bot conservando tu perfil actual.'
        await self.say(u,title+(f'\n{len(rows)} resultados' if rows else '\nSin resultados'),await self.buttons(scope,kbrows),edit)
    async def status(self,u,edit=False):
        checks=[]
        for name,call in [('Telegram',self.application.bot.get_me),('Hermes',self.hermes.health),('Database',lambda:self.store.get(self.scope(u)))]:
            try:await call();checks.append(name+' → OK')
            except Exception:checks.append(name+' → ERROR')
        try:v,s=await self.active(self.scope(u));checks.append('Active Chat → '+('OK' if s else 'Sin seleccionar'))
        except Exception:checks.append('Active Chat → ERROR')
        try:
            with tempfile.TemporaryFile(dir=ROOT/'data/tmp') as f:f.write(b'check')
            checks.append('Files → OK')
        except OSError:checks.append('Files → ERROR')
        checks.append('Transcription → '+('OK · '+self.config.model if self.transcriber.model is not None else 'Carga al primer audio · '+self.config.engine))
        await self.say(u,'\n'.join(checks),edit=edit)
    async def dispatch(self,u,a,edit=False):
        action=a['action'];scope=self.scope(u)
        if (action in ADMIN or action in {'select_model','select_profile','select_personality','select_bot','confirm_delete','set_toolsets','set_setting'}) and not self.config.admin(u.effective_user.id):
            await self.say(u,'Esta acción está restringida al OWNER.',edit=edit);return
        if action in ('start','home','refresh'):return await self.home(u,edit)
        if action in ('chats','search','profiles','bots','models'):return await self.listing(u,action,a.get('page',0),a.get('query',''),edit)
        if action=='help':
            return await self.say(u,'Envía texto, fotos, documentos, PDF o notas de voz.\n/start · /chats · /bots · /profiles · /models · /current\n/new · /search texto · /back · /rename título · /archive · /delete\n/regen · /branch · /tools · /settings · /status\nPara varios archivos: /attach, envía archivos y después /send instrucción.\nLas fotos de un álbum se agrupan automáticamente. Responde a un mensaje para volver a su conversación.\n/cancel cancela una petición activa.',edit=edit)
        if action=='status':return await self.status(u,edit)
        if action=='current':return await self.say(u,await self.current_text(scope),edit=edit)
        if action=='new':
            kb=await self.buttons(scope,[[('💬 Normal',{'action':'create'})],[('🤖 Con bot',{'action':'bots'}),('👤 Con perfil',{'action':'profiles'})],[('❌ Cancelar',{'action':'home'})]])
            return await self.say(u,'Nuevo chat',kb,edit)
        if action=='create':
            v=await self.store.get(scope);s=await self.hermes.create(v['profile']);await self.store.activate(scope,s['session_id'],v['profile'])
            return await self.home(u,edit)
        if action=='select_chat':
            await self.hermes.chat(a['sid'],a['profile'])
            v=await self.store.get(scope)
            if a['profile']!=v['profile']:await self.store.activate_bot(scope,a['sid'],a['profile'],a['profile'])
            else:await self.store.activate(scope,a['sid'],a['profile'])
            return await self.home(u,edit)
        if action=='select_bot':
            s=await self.hermes.bot_chat(a['profile'])
            await self.store.activate_bot(scope,s['session_id'],a['profile'],a['name'])
            v=await self.store.get(scope);v['bot_native']=True;await self.store.set(scope,v)
            return await self.home(u,edit)
        if action=='select_profile':
            s=await self.hermes.create(a['profile']);await self.store.activate(scope,s['session_id'],a['profile'])
            return await self.home(u,edit)
        if action=='select_personality':
            v=await self.store.get(scope);s=await self.hermes.create(v['profile'],a['name']);await self.store.activate(scope,s['session_id'],v['profile'])
            return await self.home(u,edit)
        if action=='select_model':
            v,s=await self.active(scope,True)
            if v.get('bot_native'):
                await self.hermes.native.request('POST','/api/sessions/'+v['sid']+'/model',session_profile(v),json={'model':a['model']['id'],'provider':a['model']['provider']})
                return await self.home(u,edit)
            # This endpoint is the WebUI's durable per-session model selection.
            await self.hermes.request('POST','/api/session/update',session_profile(v),json={'session_id':v['sid'],'model':a['model']['id'],'model_provider':a['model']['provider']})
            return await self.home(u,edit)
        if action=='back':
            await self.store.back(scope);return await self.home(u,edit)
        if action=='open' or action=='open_new':
            profiles=match_name([dict(p,name=p['label']) for p in await self.hermes.bots()],a['query'])
            personalities=match_name(await self.hermes.personalities((await self.store.get(scope))['profile']),a['query'])
            chats=match_name(await self.hermes.chats(),a['query'])
            if profiles and len(profiles)==1:await self.dispatch(u,{'action':'select_bot','profile':Path(profiles[0]['path']).name if not profiles[0]['is_default'] else 'default','name':profiles[0]['label']},edit)
            elif personalities and len(personalities)==1:await self.dispatch(u,{'action':'select_personality','name':personalities[0]['name']},edit)
            elif action!='open_new' and len(chats)==1:await self.dispatch(u,{'action':'select_chat','sid':chats[0]['session_id'],'profile':chats[0].get('profile') or 'default'},edit)
            else:
                await self.say(u,'No hay una coincidencia única. Elige el contexto en el menú.',edit=edit)
                return await self.listing(u,'bots',edit=False)
            if a.get('message'):return await self.converse(u,a['message'],[])
            return
        if action in ('rename','archive','delete','confirm_delete','branch','regen','export'):
            v,s=await self.active(scope)
            if not s:return await self.say(u,'Selecciona un chat primero.',edit=edit)
            if action=='delete':
                kb=await self.buttons(scope,[[('🗑 Sí, eliminar',{'action':'confirm_delete','sid':v['sid'],'profile':session_profile(v)})],[('❌ Cancelar',{'action':'home'})]])
                return await self.say(u,'¿Eliminar «'+(s.get('title') or v['sid'])+'»?',kb,edit)
            if action=='confirm_delete':
                # Confirm the captured resource, never the possibly changed active chat.
                await self.hermes.mutate('delete',a['sid'],a['profile'])
                if v['sid']==a['sid']:v['sid']=None;await self.store.set(scope,v)
                return await self.home(u,edit)
            if action=='rename':
                if not a.get('query'):return await self.say(u,'Usa /rename nuevo título',edit=edit)
                await self.hermes.mutate('rename',v['sid'],session_profile(v),title=a['query']);return await self.home(u,edit)
            if action=='archive':
                await self.hermes.mutate('archive',v['sid'],session_profile(v));v['sid']=None;await self.store.set(scope,v);return await self.home(u,edit)
            if action=='branch':
                result=await self.hermes.mutate('branch',v['sid'],session_profile(v))
                s=result.get('session',result)
                if v.get('bot_profile'):await self.store.activate_bot(scope,s['session_id'],session_profile(v),v.get('bot',session_profile(v)))
                else:await self.store.activate(scope,s['session_id'],v['profile'])
                return await self.home(u,edit)
            if action=='regen':return await self.converse(u,None,[],regen=True)
            if action=='export':
                result=s if v.get('bot_native') else await self.hermes.request('GET','/api/session/export',session_profile(v),params={'session_id':v['sid'],'format':'json'})
                return await u.effective_message.reply_document(io.BytesIO(json.dumps(result,ensure_ascii=False,indent=2).encode()),filename='conversation.json')
        if action=='tools':
            v,s=await self.active(scope);d=await self.hermes.tools(session_profile(v))
            ts=d['toolsets'];names=list(ts) if isinstance(ts,dict) else [x if isinstance(x,str) else x.get('name',x.get('id','')) for x in ts]
            text='🛠 Toolsets de Hermes\n'+('\n'.join(names) or 'Sin inventario disponible')+'\n\nMCP\n'+('\n'.join(t.get('name','') for t in d['mcp']) or 'Sin tools MCP conocidas en este perfil')
            rows=[[('Heredar tools del perfil',{'action':'set_toolsets','names':None})]]
            if names:rows += [[('Sólo '+name,{'action':'set_toolsets','names':[name]})] for name in names[:15]]
            if v.get('bot_native'):
                rows=[];text+='\n\nEste bot usa las herramientas configuradas en su perfil Hermes.'
            rows.append([('🏠 Inicio',{'action':'home'})])
            return await self.say(u,text[:3800],await self.buttons(scope,rows),edit)
        if action=='set_toolsets':
            v,s=await self.active(scope,True)
            if v.get('bot_native'):return await self.say(u,'El Bot Chat usa las herramientas de su perfil Hermes. Configúralas en Hermes.',edit=edit)
            await self.hermes.request('POST','/api/session/toolsets',session_profile(v),json={'session_id':v['sid'],'toolsets':a['names']});return await self.home(u,edit)
        if action=='providers':
            v=await self.store.get(scope);models=await self.hermes.models(session_profile(v));names=sorted({m['provider'] for m in models})
            return await self.say(u,'Proveedores con modelos\n'+'\n'.join(names)+'\nSelecciona el proveedor junto con su modelo en /models.',edit=edit)
        if action=='settings':
            v,s=await self.active(scope);d=await self.hermes.request('GET','/api/settings',session_profile(v))
            safe={k:d[k] for k in ('max_tokens','reasoning_effort','streaming','show_cli_sessions','show_previous_messaging_sessions','show_cron_sessions') if k in d}
            rows=[[('Alternar '+k,{'action':'set_setting','key':k,'value':not val})] for k,val in safe.items() if isinstance(val,bool) and k.startswith('show_')]
            rows.append([('🏠 Inicio',{'action':'home'})])
            return await self.say(u,'⚙️ Ajustes reales de Web UI\n'+json.dumps(safe,ensure_ascii=False,indent=2)+'\nLos ajustes de visibilidad son compartidos con Web UI.',await self.buttons(scope,rows),edit)
        if action=='set_setting':
            if a['key'] not in ('show_cli_sessions','show_previous_messaging_sessions','show_cron_sessions'):raise ValueError('Ajuste inválido')
            v=await self.store.get(scope);await self.hermes.request('POST','/api/settings',session_profile(v),json={a['key']:a['value']});return await self.dispatch(u,{'action':'settings'},edit)
        if action=='attach':
            self.pending[scope]=[];return await self.say(u,'Envía los archivos; después /send instrucción. /cancel descarta la selección.')
        if action=='send':
            messages=self.pending.pop(scope,[])
            if not messages:return await self.say(u,'No hay archivos preparados. Usa /attach primero.')
            return await self.process_media(messages,prompt=a.get('query') or 'Analiza los archivos adjuntos.')
        if action=='cancel':
            self.pending.pop(scope,None)
            v=await self.store.get(scope);run=self.running.get(scope)
            if isinstance(run,dict):await self.hermes.native.stop(run)
            elif run:await self.hermes.request('GET','/api/chat/cancel',session_profile(v),params={'stream_id':run})
            return await self.say(u,'Cancelado. La conversación se conserva.')
        if action in ('approval_response','clarify_response'):
            if not self.config.admin(u.effective_user.id):return await self.say(u,'Sólo el OWNER puede responder a Hermes.')
            endpoint='/api/approval/respond' if action=='approval_response' else '/api/clarify/respond'
            if a.get('native'):
                await self.hermes.native.request('POST','/v1/runs/'+a['body']['run_id']+'/approval',a['profile'],json={'choice':a['body']['choice']})
            else:await self.hermes.request('POST',endpoint,a['profile'],json=a['body'])
            return await self.say(u,'Respuesta enviada a Hermes.',edit=edit)
        if action=='message':return await self.converse(u,a.get('message',''),[])
    async def command(self,u,context):
        if not self.accepted(u):return
        cmd=u.effective_message.text.split()[0][1:].split('@')[0];query=' '.join(context.args)
        action={'chat':'chats','bot':'bots','profile':'profiles','model':'models'}.get(cmd,cmd)
        if query and cmd in ('chat','bot'):
            action='open'
        if query and cmd=='profile':
            return await self.handle(u,{'action':'select_profile','profile':query})
        await self.handle(u,{'action':action,'query':query})
    async def callback(self,u,context):
        if not self.accepted(u):
            await u.callback_query.answer('Sin permisos',show_alert=True);return
        await u.callback_query.answer()
        a=await self.store.resolve(self.scope(u),u.callback_query.data)
        if a is None:return await self.say(u,'Este botón caducó. Abre /home.',edit=True)
        if a['action']=='confirm_delete':
            a=await self.store.resolve(self.scope(u),u.callback_query.data,consume=True)
            if a is None:return
        await self.handle(u,a,edit=True)
    async def handle(self,u,a,edit=False):
        if not await self.store.claim(u.update_id):return
        try:
            if a['action'] in ('cancel','approval_response','clarify_response','status','help','current'):await self.dispatch(u,a,edit)
            else:
                async with self.locks.setdefault(self.scope(u),asyncio.Lock()):await self.dispatch(u,a,edit)
            await self.store.done(u.update_id);await self.store.metric(a['action'])
        except Exception as e:
            log.warning('request failed action=%s error=%s',a['action'],type(e).__name__)
            await self.say(u,str(e) if isinstance(e,(BackendError,ValueError)) else 'La petición falló. Consulta /status. Revisa la conversación antes de reenviar para evitar duplicar la tarea.')
            await self.store.done(u.update_id)
    async def message(self,u,context):
        if not self.accepted(u):return
        m=u.effective_message
        if m.photo or m.document or m.voice or m.audio or m.video:
            if not await self.store.claim(u.update_id):return
            scope=self.scope(u)
            if scope in self.pending:
                self.pending[scope].append(u);await self.store.done(u.update_id)
                return await self.say(u,f'Adjunto preparado ({len(self.pending[scope])}). Usa /send instrucción.')
            if m.media_group_id:
                self.groups.add(scope+':'+m.media_group_id,u,self.safe_media)
                return
            return await self.safe_media([u])
        text=(m.text or '').replace('@'+self.application.bot.username,'').strip()
        route=intent(text)
        await self.handle(u,{'action':route.action,'query':route.query,'message':route.message})
    async def safe_media(self,updates):
        try:
            async with self.locks.setdefault(self.scope(updates[0]),asyncio.Lock()):await self.process_media(updates)
            for u in updates:await self.store.done(u.update_id)
        except Exception as e:
            log.warning('media failed error=%s',type(e).__name__)
            await self.say(updates[0],str(e) if isinstance(e,(BackendError,ValueError)) else 'No pude procesar el adjunto. Revisa /status y la conversación antes de reenviar.')
            for u in updates:await self.store.done(u.update_id)
    async def process_media(self,updates,prompt=None):
        u=updates[0];scope=self.scope(u)
        with tempfile.TemporaryDirectory(prefix='media-',dir=ROOT/'data/tmp') as directory:
            atts=[]
            for update in updates:
                att=await download(self.application.bot,update.effective_message,Path(directory))
                if att:atts.append(att)
            text=prompt or '\n'.join(dict.fromkeys(x.effective_message.caption for x in updates if x.effective_message.caption))
            if len(atts)==1 and atts[0].audio:
                await self.say(u,'🎙 Transcribiendo audio…')
                transcript=await self.transcriber.transcribe(atts[0]);await self.store.metric('audio_transcribed')
                if not transcript:return await self.say(u,'No detecté voz comprensible. Puedes volver a grabar o enviar texto.')
                if len(transcript)>3000:
                    await u.effective_message.reply_document(io.BytesIO(transcript.encode()),filename='transcripcion.txt')
                if not text:
                    route=intent(transcript)
                    if route.action!='message':return await self.dispatch(u,{'action':route.action,'query':route.query,'message':route.message})
                    text=transcript
                else:text=text+'\n\nTranscripción del audio:\n'+transcript
                # Keep original audio attached for Hermes tools, plus locally transcribed intent.
            text=text or ('Analiza las imágenes adjuntas.' if all(a.image for a in atts) else 'Recibí los archivos adjuntos. Examina su contenido y describe brevemente qué contienen sin asumir otra tarea.')
            await self.converse(u,text,atts,source_updates=updates)
    async def typing(self,u):
        while True:
            try:await self.application.bot.send_chat_action(u.effective_chat.id,'typing',message_thread_id=u.effective_message.message_thread_id)
            except TelegramError:pass
            await asyncio.sleep(4)
    async def converse(self,u,text,atts,regen=False,source_updates=None):
        scope=self.scope(u);reply=u.effective_message.reply_to_message
        if reply:
            mapping=await self.store.lookup(u.effective_chat.id,reply.message_id,scope)
            if mapping:
                v=await self.store.get(scope)
                if mapping.get('native') or mapping['profile']!=v['profile']:
                    await self.store.activate_bot(scope,mapping['sid'],mapping['profile'],mapping['profile'])
                else:await self.store.activate(scope,mapping['sid'],mapping['profile'])
                if mapping.get('native'):
                    v=await self.store.get(scope);v['bot_native']=True;await self.store.set(scope,v)
                if mapping.get('hermes_mid') and text:
                    text=f'[Respuesta al mensaje Hermes {mapping["hermes_mid"]}; usa el historial existente como contexto]\n'+text
        v,s=await self.active(scope,True)
        async with self.session_locks.setdefault((session_profile(v),v['sid']),asyncio.Lock()):
            typing=asyncio.create_task(self.typing(u));self.tasks.add(typing)
            try:
                uploaded=[await self.hermes.upload(v['sid'],session_profile(v),a) for a in atts]
                for update in source_updates or [u]:
                    await self.store.map(update.effective_chat.id,update.effective_message.message_id,scope,session_profile(v),v['sid'],attachments=uploaded,native=v.get('bot_native',False))
                started=await self.hermes.start(v['sid'],session_profile(v),text,uploaded,regen=regen)
                stream=started.get('stream_id')
                if not stream:raise BackendError('Hermes no inició un stream')
                self.running[scope]=stream
                status=await self.say(u,'Hermes está procesando tu petición…')
                last_edit=0;partial='';errors=[];completed=None;cancelled=False
                async for event,data in self.hermes.events(stream,session_profile(v)):
                    if event=='token':
                        delta=data.get('text',data.get('token',data.get('delta',''))) if isinstance(data,dict) else str(data)
                        partial+=str(delta)
                        if partial and time.monotonic()-last_edit>1.5:
                            try:await status.edit_text(partial[-3500:]);last_edit=time.monotonic()
                            except TelegramError:pass
                    elif event in ('tool_start','tool_call','tool'):
                        if time.monotonic()-last_edit>1.5:
                            try:await status.edit_text('🛠 '+str(data.get('name',data.get('tool','Herramienta Hermes'))));last_edit=time.monotonic()
                            except TelegramError:pass
                    elif event=='approval':
                        body={'session_id':v['sid']}
                        for key in ('approval_id','run_id','mirror_token'):
                            if data.get(key):body[key]=data[key]
                        rows=[[('Permitir una vez',{'action':'approval_response','profile':session_profile(v),'native':data.get('native',False),'body':dict(body,choice='once')}),
                               ('Denegar',{'action':'approval_response','profile':session_profile(v),'native':data.get('native',False),'body':dict(body,choice='deny')})]]
                        await self.say(u,'Hermes solicita aprobación:\n'+str(data.get('command',data.get('description','Acción de herramienta')))[:2400],await self.buttons(scope,rows))
                    elif event=='clarify':
                        rows=[]
                        for option in data.get('choices',data.get('options',[])):
                            label=option.get('label',str(option)) if isinstance(option,dict) else str(option)
                            rows.append([(label,{'action':'clarify_response','profile':session_profile(v),'body':{'session_id':v['sid'],'clarify_id':data.get('clarify_id',''),'response':label}})])
                        await self.say(u,'Hermes pregunta:\n'+str(data.get('question','Responde en Web UI si no hay opciones.'))[:2400],await self.buttons(scope,rows) if rows else None)
                    elif event=='done':completed=data.get('session')
                    elif event=='cancel':cancelled=True
                    elif event in ('apperror','error'):errors.append(data)
                if cancelled:
                    await status.edit_text('Petición cancelada.');return
                snapshot=completed or await self.hermes.chat(v['sid'],session_profile(v))
                messages=snapshot.get('messages',[])
                user_index=max((i for i,m in enumerate(messages) if m.get('role')=='user'),default=-1)
                assistant=next((m for m in reversed(messages[user_index+1:]) if m.get('role')=='assistant' and str(m.get('content','')).strip()),None)
                if errors:raise BackendError('Hermes informó un error durante la generación. Revisa el chat en Web UI.')
                if assistant is None:raise BackendError('Hermes terminó sin respuesta visible')
                result=assistant['content']
                if isinstance(result,list):result='\n'.join(p.get('text','') for p in result if isinstance(p,dict))
                await self.deliver(u,str(result),v['sid'],session_profile(v),status,assistant.get('id'))
                await self.store.metric('hermes_completed')
                for a in atts:await self.store.metric('image_received' if a.image else 'file_received')
            finally:
                self.running.pop(scope,None);typing.cancel();await asyncio.gather(typing,return_exceptions=True);self.tasks.discard(typing)
    async def deliver(self,u,text,sid,profile,status=None,hermes_mid=None):
        paths=output_paths(text)
        actions=extract_obsidian_telegram_actions(text)
        if actions.get('normalized_form_spaces'):
            log.info('Obsidian URI normalized reason=form_encoded_spaces')
        keyboard=Keyboard([[Button(b['text'],url=obsidian_button_url(b['url'],self.config.obsidian_bridge_url))] for b in actions['buttons']]) if actions['buttons'] else None
        rendered=actions['text'] if keyboard else text
        chunks=list(split_text(rendered if rendered.strip() else (LABEL if keyboard else 'Hermes terminó la petición.')))
        async def send_chunk(chunk,index,markup=None):
            formatted=telegram_html(chunk)
            kwargs={'parse_mode':'HTML'}
            if markup is not None:kwargs['reply_markup']=markup
            try:
                if index==0 and status:return await status.edit_text(formatted,**kwargs)
                return await u.effective_message.reply_text(formatted,**kwargs)
            except BadRequest as error:
                if markup is not None and ('protocol' in str(error).lower() or 'url' in str(error).lower()):
                    raise
                # Retry formatting as plain text with the SAME validated keyboard.
                # Protocol rejection must reach the outer fallback handler.
                kwargs.pop('parse_mode')
                if index==0 and status:return await status.edit_text(chunk,**kwargs)
                return await u.effective_message.reply_text(chunk,**kwargs)
        for i,chunk in enumerate(chunks):
            try:
                sent=await send_chunk(chunk,i,keyboard if i==0 else None)
            except BadRequest as error:
                if i!=0 or keyboard is None:raise
                # Do not log model-controlled destinations or private vault paths.
                reason=str(error).lower()
                reason_code=('unsupported_url_protocol' if 'protocol' in reason or 'url' in reason
                             else 'telegram_bad_request')
                log.warning('Obsidian inline keyboard rejected reason=%s',reason_code)
                # No message was accepted: restore the entire original response.
                # send_chunk preserves the previous HTML/plain-text behavior.
                for j,original in enumerate(split_text(text)):
                    fallback=await send_chunk(original,j)
                    await self.store.map(fallback.chat_id,fallback.message_id,self.scope(u),profile,sid,hermes_mid,native=sid in self.hermes.native.sessions)
                break
            await self.store.map(sent.chat_id,sent.message_id,self.scope(u),profile,sid,hermes_mid,native=sid in self.hermes.native.sessions)
        for path in paths:
            try:
                data,mime=await self.hermes.download(path,sid,profile)
                filename=Path(path).name or 'attachment.bin';file=io.BytesIO(data)
                if mime.startswith('image/') and mime not in ('image/svg+xml','image/gif'):
                    try:sent=await u.effective_message.reply_photo(file,caption=filename)
                    except BadRequest:sent=await u.effective_message.reply_document(io.BytesIO(data),filename=filename)
                elif mime.startswith('audio/'):
                    sent=await u.effective_message.reply_audio(file,filename=filename)
                else:sent=await u.effective_message.reply_document(file,filename=filename)
                await self.store.map(sent.chat_id,sent.message_id,self.scope(u),profile,sid,hermes_mid,native=sid in self.hermes.native.sessions)
                await self.store.metric('output_image' if mime.startswith('image/') else 'output_file')
            except Exception as e:
                log.warning('output delivery failed error=%s',type(e).__name__)
                await self.say(u,'No pude entregar el adjunto '+Path(path).name+'. Puede no estar disponible o superar 50 MB.')
    async def error(self,u,context):
        # Never log exception strings or HTTP URLs: Telegram URLs contain the token.
        log.warning('telegram handler error=%s',type(context.error).__name__)

def build(config=None):
    gateway=Gateway(config or Config.load())
    app=(Application.builder().token(gateway.config.token).concurrent_updates(32)
        .rate_limiter(AIORateLimiter(max_retries=3)).post_init(gateway.start).post_shutdown(gateway.close)
        .connection_pool_size(64).get_updates_read_timeout(40).build())
    gateway.application=app
    for cmd in COMMANDS:app.add_handler(CommandHandler(cmd,gateway.command))
    app.add_handler(CallbackQueryHandler(gateway.callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND,gateway.message))
    app.add_error_handler(gateway.error)
    return app,gateway

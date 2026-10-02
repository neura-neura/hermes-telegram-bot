"""Controlled real Hermes requests + real Telegram delivery. Not forged incoming updates."""
import asyncio,json,io,tempfile,time,re
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw
from telegram import Bot,Message,Chat,User
from app.config import Config,ROOT
from app.hermes import HermesClient
from app.media import Attachment,Transcriber,mime_type
from app.storage import Storage
from app.bot import Gateway
REPORT=ROOT/'docs/validation.json'

def simple_pdf(path,text):
    stream=f'BT /F1 18 Tf 40 750 Td ({text}) Tj ET'.encode()
    objs=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    out=b'%PDF-1.4\n';offsets=[0]
    for n,obj in enumerate(objs,1):offsets.append(len(out));out+=f'{n} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(out);out+=f'xref\n0 {len(objs)+1}\n0000000000 65535 f \n'.encode()
    out+=b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:]);out+=f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode();path.write_bytes(out)

async def main():
 c=Config.load();h=HermesClient(c);report={'method':'Controlled API integration with real Hermes and real Telegram delivery; genuine inbound reception is tracked separately','started':time.time()}
 async def record(name,fn):
  try:
   detail=await fn();report[name]={'status':'PASS','detail':detail}
  except Exception as e:report[name]={'status':'FAIL','error':type(e).__name__,'detail':str(e)[:250]}
  REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(name,report[name]['status'],flush=True)
 async with Bot(c.token) as bot:
  await bot.send_message(c.owner,'El gateway está activo. Estoy ejecutando pruebas de integración en conversaciones separadas; tus archivos se procesan en tu chat actual.')
  s=await h.create();sid=s['session_id'];await h.mutate('rename',sid,'default',title='Validación controlada Telegram '+sid)
  async def turn(prompt,atts=[]):
   uploaded=[await h.upload(sid,'default',a) for a in atts]
   d=await h.start(sid,'default',prompt,uploaded)
   seen=[];completed=None
   async for event,data in h.events(d['stream_id'],'default'):
    seen.append(event)
    if event=='done':completed=data.get('session')
    if event in ('apperror','error'):raise RuntimeError('Hermes run failed')
   snap=completed or await h.chat(sid,'default')
   message=next(m for m in reversed(snap['messages']) if m.get('role')=='assistant' and str(m.get('content','')).strip())
   return message['content'],seen
  async def text():
   answer,events=await turn('Responde exactamente TEXT_GATEWAY_OK sin tools.')
   assert 'TEXT_GATEWAY_OK' in answer;assert 'token' in events and 'done' in events
   await bot.send_message(c.owner,'Prueba de texto Hermes → Telegram: '+answer)
   return 'Native SSE tokens, done, persisted response; Telegram sendMessage delivered'
  await record('text_streaming',text)
  with tempfile.TemporaryDirectory(dir=ROOT/'data/tmp') as directory:
   directory=Path(directory);paths=[]
   for color in ('red','green','blue'):
    p=directory/(color+'.png');im=Image.new('RGB',(320,240),color);ImageDraw.Draw(im).rectangle((110,70,210,170),fill='white');im.save(p);paths.append(p)
   att=lambda p:Attachment(p,p.name,mime_type(p.name),p.stat().st_size,'fixture')
   async def photo():
    answer,_=await turn('Describe la imagen en español. ¿De qué color es el fondo y qué figura hay en el centro?', [att(paths[0])])
    assert 'roj' in answer.lower() and any(w in answer.lower() for w in ('cuadr','rectang'))
    return 'Image content recognized beyond prompt; native attachment persisted'
   await record('image_caption',photo)
   async def no_caption():
    answer,_=await turn('Analiza la imagen adjunta.',[att(paths[2])]);assert 'azul' in answer.lower();return 'Blue image recognized with neutral prompt'
   await record('image_no_caption',no_caption)
   async def album():
    answer,_=await turn('Compara las tres imágenes: indica el color del fondo de cada una.',[att(p) for p in paths])
    assert all(w in answer.lower() for w in ('roj','verde','azul'));return 'Three original images uploaded in one Hermes turn'
   await record('three_images_one_turn',album)
   pdf=directory/'reference.pdf';simple_pdf(pdf,'HERMES CHECK: Project ORION budget 7342 dollars.')
   async def pdf_test():
    answer,events=await turn('Lee el PDF adjunto y dime el proyecto y su presupuesto.',[att(pdf)])
    assert 'ORION' in answer.upper() and ('7342' in answer or '7,342' in answer or '7.342' in answer)
    return 'Original PDF uploaded and content-derived budget recognized; tools='+str('tool' in events)
   await record('pdf_content',pdf_test)
   code=directory/'sample.py';code.write_text('def quotient(a, b):\n    return a / 0\n')
   async def code_test():
    answer,_=await turn('Encuentra el error del archivo Python adjunto.',[att(code)]);assert 'cero' in answer.lower() or 'zero' in answer.lower();return 'Original code attachment analyzed'
   await record('code_content',code_test)
   first=directory/'a.csv';first.write_text('month,value\nJan,41\n');second=directory/'b.csv';second.write_text('month,value\nFeb,72\n')
   async def multi():
    answer,_=await turn('Lee los dos CSV adjuntos. Dime el valor de cada mes y su suma.',[att(first),att(second)])
    assert '113' in answer;return 'Two CSV originals associated with one instruction'
   await record('multiple_files',multi)
   async def outputs():
    prompt='Usa una herramienta de Hermes para crear en /Users/neura/workspace/hermes-telegram-validation un CSV con columnas item,value y fila verified,123, y una imagen PNG de 120x120 con fondo amarillo. Debes producir los dos archivos reales. Puedes usar Python, zlib y struct de la biblioteca estándar para escribir el PNG si Pillow no está disponible. Al terminar devuelve texto breve y enlaces Markdown a las rutas absolutas de ambos archivos, sin bloques de código.'
    answer,events=await turn(prompt)
    from app.formatting import output_paths
    paths=output_paths(answer);assert len(paths)>=2, 'Hermes did not expose generated paths'
    # The adapter's real output pipeline sends actual bytes through Telegram.
    g=Gateway(c);await g.store.open();g.hermes=h
    message=Message.de_json({'message_id':1,'date':int(time.time()),'chat':{'id':c.owner,'type':'private'},'from':{'id':c.owner,'is_bot':False,'first_name':'Owner'}},bot)
    u=SimpleNamespace(effective_message=message,effective_chat=message.chat,effective_user=message.from_user)
    g.application=SimpleNamespace(bot=bot)
    try:await g.deliver(u,'Prueba de respuesta mixta:\n'+answer,sid,'default')
    finally:await g.store.close()
    types=[]
    for path in paths:
     data,mime=await h.download(path,sid,'default');assert data;types.append(mime)
    assert any(t.startswith('image/') for t in types) and any('csv' in t for t in types)
    return 'Hermes tools generated files; Telegram delivered text + image + CSV bytes; events='+','.join(sorted(set(events)))
   await record('generated_mixed_outputs',outputs)
  async def crud():
   temp=await h.create();tsid=temp['session_id'];await h.mutate('rename',tsid,'default',title='CRUD check '+tsid)
   started=await h.start(tsid,'default','Responde CRUD_OK. No uses herramientas.')
   async for _ in h.events(started['stream_id'],'default'):pass
   assert any(row['session_id']==tsid for row in await h.chats())
   assert (await h.chat(tsid,'default'))['title'].startswith('CRUD check')
   await h.request('POST','/api/session/update',json={'session_id':tsid,'model':'gpt-6-luna','model_provider':'openai-api'})
   branch=(await h.mutate('branch',tsid,'default'))['session_id']
   await h.mutate('archive',branch,'default')
   # Disposable test resources only; no user conversations deleted.
   await h.mutate('delete',branch,'default');await h.mutate('delete',tsid,'default')
   return 'Create/list/rename/model update/branch/archive/delete on disposable WebUI sessions'
  await record('crud_webui_sync',crud)
  async def profile_test():
   p=await h.profiles();assert any(r['name']=='little-k' for r in p)
   personalities=await h.personalities('default');assert personalities
   return f'{len(p)} live profiles incl. little-k; {len(personalities)} real personalities'
  await record('profiles_bots',profile_test)
 await h.close();report['finished']=time.time();REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print('Report',REPORT,flush=True)
if __name__=='__main__':asyncio.run(main())

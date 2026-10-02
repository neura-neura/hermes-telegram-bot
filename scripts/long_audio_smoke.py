import asyncio,tempfile,json
from pathlib import Path
from telegram import Bot
from app.config import ROOT,Config
from app.hermes import HermesClient
from app.media import Transcriber,Attachment
async def command(*args):
 p=await asyncio.create_subprocess_exec(*args,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL);await p.wait()
 if p.returncode:raise RuntimeError('Audio generation failed')
async def main():
 c=Config.load();h=HermesClient(c);t=Transcriber(c,h)
 try:
  with tempfile.TemporaryDirectory(dir=ROOT/'data/tmp') as td:
   td=Path(td);src=td/'meeting.aiff';ogg=td/'meeting.ogg'
   speech='Comienza la reunión del proyecto Hermes. Ana confirma que el presupuesto es de doce mil setecientos pesos. Luis debe entregar el informe el viernes. El equipo acuerda probar las imágenes y los documentos antes de publicar. Hay tres tareas pendientes: revisar el presupuesto, preparar el informe y verificar los archivos. La próxima reunión será el lunes. Terminamos la reunión con estos acuerdos. '
   await command('/usr/bin/say','-v','Paulina','-r','130','-o',str(src),speech*3)
   await command('/opt/homebrew/bin/ffmpeg','-v','error','-y','-i',str(src),'-c:a','libopus',str(ogg))
   text=await t.transcribe(Attachment(ogg,'meeting.ogg','audio/ogg',ogg.stat().st_size))
   assert 'informe' in text.lower() and 'presupuesto' in text.lower()
   session=await h.create();d=await h.start(session['session_id'],'default','Resume los acuerdos y las tareas de esta transcripción:\n'+text)
   snapshot=None
   async for event,data in h.events(d['stream_id'],'default'):
    if event=='done':snapshot=data.get('session')
   snapshot=snapshot or await h.chat(session['session_id'],'default')
   answer=next(m['content'] for m in reversed(snapshot['messages']) if m.get('role')=='assistant' and str(m.get('content','')).strip())
   assert 'informe' in answer.lower() and 'presupuesto' in answer.lower()
   async with Bot(c.token) as bot:
    await bot.send_document(c.owner,text.encode(),filename='prueba_transcripcion_reunion.txt',caption='Prueba controlada de audio largo: transcripción local.')
    await bot.send_message(c.owner,'Prueba de resumen de audio largo por Hermes:\n'+answer)
   result={'status':'PASS','source':'synthetic Spanish meeting repeated three times','model':c.model,'transcript_characters':len(text),'summary_delivered':True}
   (ROOT/'docs/long-audio-validation.json').write_text(json.dumps(result,indent=2));print('Long audio PASS',flush=True)
 finally:await h.close()
asyncio.run(main())

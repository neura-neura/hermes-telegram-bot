import fcntl,logging,os
from logging.handlers import RotatingFileHandler
from app.config import ROOT
from app.bot import build

def main():
    os.umask(0o077)
    for name in ('data/tmp','logs'):(ROOT/name).mkdir(parents=True,exist_ok=True)
    lock=(ROOT/'data/service.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('El gateway ya está ejecutándose')
    handler=RotatingFileHandler(ROOT/'logs/gateway.log',maxBytes=5_000_000,backupCount=4)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.basicConfig(level=logging.INFO,handlers=[handler])
    for name in ('httpx','httpcore','telegram','huggingface_hub','faster_whisper'):
        logging.getLogger(name).setLevel(logging.WARNING)
    app,_=build();logging.info('gateway startup; long polling')
    app.run_polling(drop_pending_updates=False,timeout=30,bootstrap_retries=-1,allowed_updates=['message','callback_query'])
if __name__=='__main__':main()

"""Gateway metadata only. No conversations or transcripts are copied here."""
import json, time, secrets
import aiosqlite
from app.config import ROOT

class Storage:
    async def open(self, path=None):
        self.db = await aiosqlite.connect(path or ROOT/'data/state.sqlite3')
        await self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS context (scope TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS callbacks (id TEXT PRIMARY KEY, scope TEXT, value TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS updates (id INTEGER PRIMARY KEY, status TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS mappings (chat INTEGER, mid INTEGER, scope TEXT, profile TEXT,
          sid TEXT, hermes_mid TEXT, attachments TEXT, PRIMARY KEY(chat,mid));
        CREATE TABLE IF NOT EXISTS metrics (kind TEXT PRIMARY KEY, count INTEGER, updated REAL);
        ''')
        async with self.db.execute('PRAGMA table_info(mappings)') as cursor:
            columns={row[1] for row in await cursor.fetchall()}
        if 'native' not in columns:
            await self.db.execute('ALTER TABLE mappings ADD COLUMN native INTEGER NOT NULL DEFAULT 0')
        await self.db.commit()
        return self
    async def get(self, scope):
        async with self.db.execute('SELECT value FROM context WHERE scope=?',(scope,)) as c:
            r=await c.fetchone()
        return json.loads(r[0]) if r else {'profile':'default','sid':None,'history':[]}
    async def set(self, scope, value):
        await self.db.execute('INSERT OR REPLACE INTO context VALUES (?,?)',(scope,json.dumps(value)))
        await self.db.commit()
    async def activate(self, scope, sid, profile):
        value=await self.get(scope)
        if value.get('sid') and (value['sid'],value['profile']) != (sid,profile):
            value['history']=(value.get('history',[])+[{k:value.get(k) for k in ('sid','profile','bot','bot_profile','bot_native')}])[-30:]
        value.pop('bot',None);value.pop('bot_profile',None);value.pop('bot_native',None)
        value.update(sid=sid,profile=profile)
        await self.set(scope,value)
    async def activate_bot(self, scope, sid, bot_profile, name):
        value=await self.get(scope)
        previous={k:value.get(k) for k in ('sid','profile','bot','bot_profile','bot_native')}
        if value.get('sid') and value['sid']!=sid:
            value['history']=(value.get('history',[])+[previous])[-30:]
        value.update(sid=sid,bot=name,bot_profile=bot_profile)
        await self.set(scope,value)
    async def back(self, scope):
        v=await self.get(scope)
        if v.get('history'):v.update(v['history'].pop());await self.set(scope,v)
        return v
    async def callback(self, scope, value):
        key=secrets.token_hex(8)
        await self.db.execute('INSERT INTO callbacks VALUES (?,?,?,?)',(key,scope,json.dumps(value),time.time()+86400))
        await self.db.commit();return key
    async def resolve(self, scope, key, consume=False):
        query=('DELETE FROM callbacks WHERE id=? AND scope=? AND expires>? RETURNING value' if consume
               else 'SELECT value FROM callbacks WHERE id=? AND scope=? AND expires>?')
        async with self.db.execute(query,(key,scope,time.time())) as c:
            r=await c.fetchone()
        if consume:await self.db.commit()
        return json.loads(r[0]) if r else None
    async def claim(self, uid):
        c=await self.db.execute('INSERT OR IGNORE INTO updates VALUES (?, ?, ?)',(uid,'processing',time.time()))
        await self.db.commit();return c.rowcount == 1
    async def done(self, uid):
        await self.db.execute('UPDATE updates SET status=? WHERE id=?',('done',uid));await self.db.commit()
    async def map(self, chat, mid, scope, profile, sid, hermes_mid=None, attachments=None, native=False):
        await self.db.execute('INSERT OR REPLACE INTO mappings (chat,mid,scope,profile,sid,hermes_mid,attachments,native) VALUES (?,?,?,?,?,?,?,?)',
            (chat,mid,scope,profile,sid,str(hermes_mid or ''),json.dumps(attachments or []),int(native)))
        await self.db.commit()
    async def lookup(self, chat, mid, scope):
        async with self.db.execute('SELECT profile,sid,hermes_mid,attachments,native FROM mappings WHERE chat=? AND mid=? AND scope=?',(chat,mid,scope)) as c:
            r=await c.fetchone()
        return {'profile':r[0],'sid':r[1],'hermes_mid':r[2],'attachments':json.loads(r[3]),'native':bool(r[4])} if r else None
    async def metric(self, kind):
        await self.db.execute('INSERT INTO metrics VALUES (?,1,?) ON CONFLICT(kind) DO UPDATE SET count=count+1,updated=excluded.updated',(kind,time.time()));await self.db.commit()
    async def cleanup(self):
        await self.db.execute('DELETE FROM callbacks WHERE expires<?',(time.time(),))
        await self.db.execute('DELETE FROM updates WHERE created<?',(time.time()-30*86400,));await self.db.commit()
    async def close(self): await self.db.close()

import re,unicodedata
from dataclasses import dataclass

def normalized(text):return ''.join(c for c in unicodedata.normalize('NFD',text.casefold()) if unicodedata.category(c)!='Mn').strip(' .!?¿¡')
@dataclass
class Intent:
    action: str
    query: str=''
    message: str=''

def intent(text):
    n=normalized(text)
    if n in ('deja de hablar con el bot y abre una conversacion en mi perfil actual',
             'sal del bot','salir del bot','deja de hablar con el bot',
             'abre una conversacion en mi perfil actual','abre un chat normal',
             'inicia una conversacion normal','quiero hablar en mi perfil actual'):
        return Intent('create')
    if n in ('新建聊天','请新建聊天','new chat'):return Intent('new')
    if n in ('显示我的机器人','显示机器人'):return Intent('bots')
    lists={'chats':'chats','conversaciones':'chats','bots':'bots','perfiles':'profiles','modelos':'models','herramientas':'tools','profiles':'profiles','models':'models','tools':'tools'}
    for word,action in lists.items():
        if re.fullmatch(r'(muestrame|muestra|lista|ver|show|list)( mis| los| my)? '+word,n):return Intent(action)
    if n in ('regresa al anterior','vuelve al anterior','regresa al chat anterior','back'):return Intent('back')
    if n in ('que bot estoy usando','que perfil estoy usando','chat actual'):return Intent('current')
    if re.fullmatch(r'(abre|crea|quiero) (un )?chat nuevo',n):return Intent('new')
    m=re.match(r'busca (?:el )?chat (?:donde hablabamos de |de )?(.+)',n)
    if m:return Intent('search',m[1])
    m=re.match(r'abre un chat nuevo con (.+)',text.strip(),re.I)
    if m:return Intent('open_new',m[1])
    m=re.match(r'(?:quiero hablar con|abre|cambia al bot(?: de)?) (.+)',text.strip(),re.I)
    if m:
        pieces=re.split(r' y (?:preg[uú]ntale|dile) ',m[1],maxsplit=1,flags=re.I)
        return Intent('open',re.sub(r'^(?:el chat |el del |el de )','',pieces[0],flags=re.I),pieces[1] if len(pieces)>1 else '')
    return Intent('message',message=text)

def match_name(rows,query):
    q=normalized(query).replace(' ','-')
    exact=[r for r in rows if normalized(r.get('name') or r.get('title') or '').replace(' ','-')==q]
    if exact:return exact
    return [r for r in rows if q in normalized(r.get('name') or r.get('title') or '').replace(' ','-')]

import html,re

def split_text(text,limit=3800):
    # Limit by UTF-16 units as well as code points (Telegram entities use UTF-16).
    while text:
        n=0;units=0
        for c in text:
            units+=2 if ord(c)>0xffff else 1
            if units>limit:break
            n+=1
        if n==len(text):yield text;return
        prefix=text[:n]
        cut=max(prefix.rfind('\n\n'),prefix.rfind('\n'))
        if cut<n//3:
            matches=list(re.finditer(r'[.!?。！？]\s',prefix))
            cut=matches[-1].end() if matches else prefix.rfind(' ')
        if cut<n//3:cut=n
        yield text[:cut];text=text[cut:]

def telegram_html(text):
    # Escape first, then convert a deliberately small, safe Markdown subset.
    text=html.escape(text)
    code=[]
    def fence(m):
        code.append('<pre>'+m[2]+'</pre>');return f'\x00{len(code)-1}\x00'
    text=re.sub(r'```([^\n`]*)\n([\s\S]*?)```',fence,text)
    text=re.sub(r'`([^`\n]+)`',r'<code>\1</code>',text)
    text=re.sub(r'\*\*([^*\n]+)\*\*',r'<b>\1</b>',text)
    text=re.sub(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)',r'<a href="\2">\1</a>',text)
    return re.sub(r'\x00(\d+)\x00',lambda m:code[int(m[1])],text)

def output_paths(text):
    """Explicit media markers, local Markdown links and code-formatted absolute paths."""
    paths=[]
    for m in re.finditer(r'MEDIA:\s*([^\n]+)',text):
        p=m[1].strip().strip('`\"\'');paths.append(p)
    for m in re.finditer(r'!?\[[^\]]*\]\(([^)]+)\)',text):
        p=m[1].strip().strip('<>')
        if p.startswith(('/', 'file://','./')):paths.append(p.removeprefix('file://'))
    # Agents sometimes correctly create a file but mention only its absolute path
    # in inline code. The native download layer independently enforces per-run
    # provenance, sensitive-path denial, symlink safety and size limits.
    for m in re.finditer(r'`(/[^`\n]+)`',text):paths.append(m[1].strip())
    return list(dict.fromkeys(paths))

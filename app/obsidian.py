"""Pure Obsidian action extraction. Destinations are validated, never rewritten."""
import re
from urllib.parse import urlsplit, unquote, quote

LABEL = 'Abrir en Obsidian'
# Query values use RFC 3986 encoding. Literal '+' is rejected (use %2B for
# a plus character); raw Unicode and whitespace must be percent encoded.
VALUE = re.compile(r"(?:[A-Za-z0-9._~!$'()*;,=:@/?-]|%[0-9A-Fa-f]{2})+\Z")
MARKDOWN = re.compile(r'(?<!!)\[([^\]\n]*)\]\((obsidian://[^\s<>]*?)\)', re.I)
BARE = re.compile(r'(?<![\w:/])obsidian://[^\s`"\[\]\\]+', re.I)


def valid_obsidian_uri(uri):
    """Closed parameter policy; return a bool without normalizing the URI."""
    try:
        if (not uri.isascii() or any(c.isspace() for c in uri) or
                not uri.startswith('obsidian://open?') or '...' in uri):
            return False
        parsed = urlsplit(uri)
        if (parsed.scheme != 'obsidian' or parsed.netloc != 'open' or
                parsed.path or parsed.fragment):
            return False
        values = {}
        for pair in parsed.query.split('&'):
            key, sep, value = pair.partition('=')
            if not sep or key not in ('vault', 'file') or key in values or not VALUE.fullmatch(value):
                return False
            decoded = unquote(value, encoding='utf-8', errors='strict')
            if (not decoded.strip() or '...' in decoded or '…' in decoded or
                    any(ord(c) < 32 or ord(c) == 127 or c in '<>' for c in decoded)):
                return False
            values[key] = value
        return set(values) == {'vault', 'file'}
    except (ValueError, UnicodeError):
        return False


def _code_ranges(text):
    """Protect fenced (including unclosed) and inline code from extraction."""
    ranges = []
    fence = None
    start = offset = 0
    for line in text.splitlines(keepends=True):
        match = re.match(r' {0,3}(`{3,}|~{3,})', line)
        if fence is None and match:
            fence = match[1]; start = offset
        elif fence is not None and re.match(r' {0,3}' + re.escape(fence[0]) +
                                            '{' + str(len(fence)) + r',}\s*$', line):
            ranges.append((start, offset + len(line))); fence = None
        offset += len(line)
    if fence is not None:
        ranges.append((start, len(text)))
    for match in re.finditer(r'(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)', text):
        ranges.append(match.span())
    return ranges


def extract_obsidian_telegram_actions(text):
    """Return {text, buttons}; only remove occurrences yielding valid actions.

    The caller must restore the original text if Telegram rejects the keyboard.
    No network calls, filesystem access, decoding/re-encoding of destinations,
    or model-controlled button labels.
    """
    protected = _code_ranges(text)
    def allowed(start, end):
        return not any(start < b and end > a for a, b in protected)
    replacements = []
    buttons = []
    seen = set()
    # Never interpret a Markdown label as a destination, even for other schemes.
    markdown_ranges = [m.span() for m in re.finditer(r'!?\[[^\]\n]*\]\([^\n]*?\)', text)]
    def add(uri, start, end):
        if not allowed(start, end) or not valid_obsidian_uri(uri):
            return
        replacements.append((start, end))
        if uri not in seen:
            seen.add(uri); buttons.append({'text': LABEL, 'url': uri})
    for match in MARKDOWN.finditer(text):
        markdown_ranges.append(match.span())
        add(match[2], *match.span())
    for match in BARE.finditer(text):
        if any(match.start() < b and match.end() > a for a, b in markdown_ranges):
            continue
        add(match[0], *match.span())
    result = text
    for start, end in sorted(replacements, reverse=True):
        result = result[:start] + result[end:]
    return {'text': result, 'buttons': buttons}


def obsidian_button_url(uri, bridge_url=''):
    """Optional HTTPS transport; fragment decodes once to the EXACT original URI."""
    if not valid_obsidian_uri(uri):
        raise ValueError('URI Obsidian inválido')
    if not bridge_url:
        return uri
    base=urlsplit(bridge_url)
    if (base.scheme!='https' or not base.hostname or base.username or base.password or
            base.query or base.fragment or base.hostname in ('localhost','127.0.0.1','::1')):
        raise ValueError('El puente Obsidian requiere una URL HTTPS pública sin query ni fragmento')
    return bridge_url+'#'+quote(uri,safe='')

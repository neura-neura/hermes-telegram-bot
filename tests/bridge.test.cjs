const test = require('node:test');
const assert = require('node:assert/strict');
const { validObsidianUri, uriFromFragment, boot } = require('../bridge/bridge.js');
const uri = 'obsidian://open?vault=Mi%20Vault&file=Carpeta/%E7%AC%94%E8%AE%B0%20%C3%B1.md';

test('fragment preserves the exact encoded destination', () => {
  assert.equal(uriFromFragment('#' + encodeURIComponent(uri)), uri);
  assert.equal(validObsidianUri(uri), true);
});

test('only closed, valid Obsidian open targets are accepted', () => {
  for (const invalid of ['javascript:alert(1)', 'https://example.com',
    'obsidian://evil?vault=A&file=B', 'obsidian://open?vault=A',
    'obsidian://open?file=B', 'obsidian://open?vault=&file=B',
    'obsidian://open?vault=A&file=a+b', 'obsidian://open?vault=A&file=...',
    'obsidian://open?vault=A&file=%FF', 'obsidian://open?vault=A&file=%3Cscript%3E',
    'obsidian://open?vault=A&file=%0A', 'obsidian://open?vault=A&file=B&x=C',
    'obsidian://open?vault=A&file=B&file=C', 'obsidian://open/path?vault=A&file=B']) {
    assert.equal(validObsidianUri(invalid), false, invalid);
    assert.equal(uriFromFragment('#' + encodeURIComponent(invalid)), null);
  }
  assert.equal(uriFromFragment('#%XX'), null);
  assert.equal(validObsidianUri('obsidian://open?vault=A&file=a%2Bb'), true);
});

function fixture(fragment, fail = false) {
  const calls = [], elements = { status: {textContent: ''}, open: {hidden: true,
    setAttribute: (key, value) => calls.push([key, value])} };
  const win = {location: {hash: fragment, assign: value => {
    calls.push(['navigate', value]); if (fail) throw new Error('Browser requires a tap');
  }}};
  return {calls, elements, win, doc: {getElementById: id => elements[id]}};
}

test('auto-open and manual button use the same original URI', () => {
  const f = fixture('#' + encodeURIComponent(uri)); boot(f.win, f.doc);
  assert.deepEqual(f.calls, [['href', uri], ['navigate', uri]]);
  assert.equal(f.elements.open.hidden, false);
});

test('browser requiring gesture retains manual button', () => {
  const f = fixture('#' + encodeURIComponent(uri), true); boot(f.win, f.doc);
  assert.equal(f.elements.open.hidden, false);
  assert.match(f.elements.status.textContent, /Pulsa/);
});

test('invalid fragments never navigate or populate a link', () => {
  const f = fixture('#' + encodeURIComponent('javascript:alert(1)')); boot(f.win, f.doc);
  assert.deepEqual(f.calls, []); assert.equal(f.elements.open.hidden, true);
});

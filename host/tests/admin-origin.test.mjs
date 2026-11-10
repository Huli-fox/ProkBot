import test from 'node:test';
import assert from 'node:assert/strict';
import { adminMutation, adminOriginFor } from '../server/security.mjs';

const canonical = 'https://127.0.0.1:18443';
const alias = 'http://127.0.0.1:18080';
const request = (origin, host = '127.0.0.1:18080', extra = {}) => ({
  headers: { origin, host, 'x-grokbot-csrf': '1', ...extra },
});

test('only an explicit same-Host administration alias is accepted', () => {
  const req = request(alias);
  assert.equal(adminOriginFor(req, canonical), canonical);
  assert.throws(() => adminMutation(req, adminOriginFor(req, canonical)), { status: 403 });
  assert.equal(adminOriginFor(req, canonical, [alias]), alias);
  assert.doesNotThrow(() => adminMutation(req, adminOriginFor(req, canonical, [alias])));
  assert.equal(adminOriginFor(request(canonical), canonical, [alias]), canonical);
});

test('administration aliases do not accept unlisted, opaque, cross-Host or forwarded origins', () => {
  const rejected = [
    request('https://untrusted.example'), request('null'), request(alias + '/'),
    request('http://127.0.0.1:18081'), request('http://localhost:18080'),
    request(alias, '127.0.0.1:18443'),
    request(alias, 'untrusted.example', { 'x-forwarded-host': '127.0.0.1:18080' }),
    request('https://untrusted.example', 'untrusted.example', { 'x-forwarded-proto': 'https' }),
  ];
  for (const req of rejected) {
    assert.throws(() => adminMutation(req, adminOriginFor(req, canonical, [alias])), { status: 403 });
  }
  const noCsrf = request(alias, '127.0.0.1:18080', { 'x-grokbot-csrf': undefined });
  assert.throws(() => adminMutation(noCsrf, adminOriginFor(noCsrf, canonical, [alias])), { status: 403 });
  assert.doesNotThrow(() => adminMutation(request(undefined), canonical));
});

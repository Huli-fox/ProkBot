import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createSelfHostServer } from '../server/index.mjs';

function post(url, headers, body) {
  // fetch ignores an overridden Host; use the HTTP client to model proxy/SSH authorities.
  return new Promise((resolve, reject) => {
    const request = http.request(url, { method: 'POST', headers }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('error', reject);
      response.on('end', () => resolve({ status: response.statusCode,
        headers: new Headers(response.headers),
        json: async () => JSON.parse(Buffer.concat(chunks).toString()) }));
    });
    request.on('error', reject);
    request.setTimeout(5000, () => request.destroy(new Error('Test HTTP request timed out')));
    request.end(JSON.stringify(body));
  });
}

test('HTTP management alias supports login and pairing while preserving the HTTPS gateway and CSRF checks', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'prokbot-admin-origin-'));
  const publicUrl = 'https://127.0.0.1:18443';
  const alias = 'http://127.0.0.1:18080';
  let app;
  try {
    app = await createSelfHostServer({ dataDir: directory, modelFile: join(directory, 'model.env'),
      internalToken: 'admin_origin_test_credential_00000000000000', publicUrl, adminOrigins: ` ${alias} ` });
    const { port } = await app.start(0, '127.0.0.1');
    const base = `http://127.0.0.1:${port}`;
    const password = 'temporary-origin-regression-password';
    await app.auth.setup(app.auth.setupKey, password);
    const send = (path, { origin = alias, host = new URL(alias).host, cookie,
      csrf = '1', body = {} } = {}) => post(base + path,
      { host, origin, 'content-type': 'application/json',
        ...(cookie ? { cookie } : {}), ...(csrf ? { 'x-grokbot-csrf': csrf } : {}) }, body);

    const login = await send('/admin/api/login', { body: { password } });
    assert.equal(login.status, 200);
    const setCookie = login.headers.get('set-cookie');
    assert.match(setCookie, /HttpOnly; SameSite=Strict/);
    assert.doesNotMatch(setCookie, /; Secure/);
    const cookie = setCookie.split(';')[0];
    const keyResponse = await send('/admin/api/pairing-keys', { cookie });
    assert.equal(keyResponse.status, 201);
    const { pairingKey } = await keyResponse.json();
    const paired = await fetch(base + '/connect/pair', { method: 'POST',
      headers: { 'content-type': 'application/json' }, body: JSON.stringify({
        pairingKey, deviceName: 'Origin regression client', platform: 'desktop' }) });
    assert.equal(paired.status, 201);
    assert.equal((await paired.json()).gatewayUrl, publicUrl);
    const session = await fetch(base + '/admin/api/session', { headers: { cookie } });
    assert.deepEqual(await session.json(), { initialized: true, authenticated: true, publicUrl });

    assert.equal((await send('/admin/api/pairing-keys', { cookie, origin: 'https://untrusted.example' })).status, 403);
    assert.equal((await send('/admin/api/pairing-keys', { cookie, host: new URL(publicUrl).host })).status, 403);
    assert.equal((await send('/admin/api/pairing-keys', { cookie, csrf: '' })).status, 403);
    assert.equal((await send('/admin/api/pairing-keys')).status, 401);

    const canonicalLogin = await send('/admin/api/login', { origin: publicUrl,
      host: new URL(publicUrl).host, body: { password } });
    assert.equal(canonicalLogin.status, 200);
    assert.match(canonicalLogin.headers.get('set-cookie'), /; Secure/);
    const canonicalCookie = canonicalLogin.headers.get('set-cookie').split(';')[0];
    assert.equal((await send('/admin/api/pairing-keys', { origin: publicUrl,
      host: new URL(publicUrl).host, cookie: canonicalCookie })).status, 201);
    const logout = await send('/admin/api/logout', { cookie });
    assert.equal(logout.status, 200);
    assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
    assert.doesNotMatch(logout.headers.get('set-cookie'), /; Secure/);
    assert.equal((await send('/admin/api/pairing-keys', { cookie })).status, 401);
  } finally {
    if (app) await app.close();
    await rm(directory, { recursive: true, force: true });
  }
});

test('unconfigured HTTP management origin remains rejected with a canonical HTTPS gateway', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'prokbot-admin-origin-default-'));
  let app;
  try {
    app = await createSelfHostServer({ dataDir: directory, modelFile: join(directory, 'model.env'),
      internalToken: 'admin_origin_test_credential_00000000000000',
      publicUrl: 'https://127.0.0.1:18443', adminOrigins: '' });
    const { port } = await app.start(0, '127.0.0.1');
    const response = await fetch(`http://127.0.0.1:${port}/admin/api/pairing-keys`, { method: 'POST',
      headers: { origin: `http://127.0.0.1:${port}`, 'x-grokbot-csrf': '1' } });
    assert.equal(response.status, 403);
    assert.deepEqual(await response.json(), { error: '请求来源不匹配' });
  } finally {
    if (app) await app.close();
    await rm(directory, { recursive: true, force: true });
  }
});

import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { once } from 'node:events';
import { createSelfHostServer } from '../server/index.mjs';

test('Android HTTP pairing authenticates RPC and SSE; revocation closes streams and invalidates the token', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'prokbot-android-http-'));
  const internalToken = 'internal_test_credential_00000000000000000';
  const observed = [];
  const upstream = http.createServer((request, response) => {
    observed.push({ path: request.url, authorization: request.headers.authorization });
    if (request.url.startsWith('/events')) {
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      response.write('data: {"kind":"connected"}\n\n');
    } else {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ value: 'from-private-host' }));
    }
  });
  upstream.listen(0, '127.0.0.1');
  await once(upstream, 'listening');
  let app;
  try {
    app = await createSelfHostServer({ dataDir: directory, modelFile: join(directory, 'model.env'),
      hostUrl: `http://127.0.0.1:${upstream.address().port}`, internalToken });
    const { port } = await app.start(0, '127.0.0.1');
    const origin = `http://127.0.0.1:${port}`;
    const { pairingKey } = await app.auth.createPairing();
    const input = { pairingKey, platform: 'android', deviceName: 'Android HTTP test' };
    const pair = () => fetch(`${origin}/connect/pair`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(input) });
    const paired = await pair();
    assert.equal(paired.status, 201);
    const { token, deviceId, gatewayUrl } = await paired.json();
    assert.equal(gatewayUrl, origin);
    assert.equal((await pair()).status, 401);
    const headers = { authorization: `Bearer ${token}`, 'content-type': 'application/json' };
    const status = await fetch(`${origin}/connect/status`, { headers });
    assert.equal((await status.json()).platform, 'android');
    const device = await fetch(`${origin}/local/device`, { method: 'PUT', headers,
      body: JSON.stringify({ kind: 'android', bundleId: 'ai.x.grok.bot', appVersion: '1.19.1', push: { provider: 'none' } }) });
    assert.equal(device.status, 200);
    assert.equal((await device.json()).kind, 'android');
    const rpc = await fetch(`${origin}/api/getHostSettings`, { method: 'POST', headers, body: '{}' });
    assert.equal(rpc.status, 200);
    assert.deepEqual(await rpc.json(), { value: 'from-private-host' });
    const events = await fetch(`${origin}/events?surface=mobile`, { headers, signal: AbortSignal.timeout(5000) });
    assert.equal(events.status, 200);
    const reader = events.body.getReader();
    assert.match(new TextDecoder().decode((await reader.read()).value), /connected/);
    await app.auth.revoke(deviceId);
    assert.equal((await fetch(`${origin}/api/getHostSettings`, { method: 'POST', headers, body: '{}' })).status, 401);
    // The administration route calls both revoke() and connections.revoke(). Exercise that route
    // with a test administrator session rather than relying on the private connections object.
    const adminToken = await app.auth.setup(app.auth.setupKey, 'temporary-android-test-password');
    const revoke = await fetch(`${origin}/admin/api/devices/${deviceId}/revoke`, { method: 'POST',
      headers: { cookie: `grokbot_admin=${adminToken}`, 'x-grokbot-csrf': '1' } });
    assert.equal(revoke.status, 200);
    const closed = await Promise.race([
      reader.read().then(value => value.done, () => true),
      new Promise(resolve => { setTimeout(() => resolve(false), 1000).unref(); }),
    ]);
    assert.equal(closed, true);
    assert.ok(observed.length >= 2);
    assert.ok(observed.every(item => item.authorization === `Bearer ${internalToken}`));
    assert.equal((await fetch(`${origin}/events?surface=mobile`, { headers })).status, 401);
  } finally {
    if (app) await app.close();
    upstream.closeAllConnections();
    await new Promise(resolve => upstream.close(resolve));
    await rm(directory, { recursive: true, force: true });
  }
});

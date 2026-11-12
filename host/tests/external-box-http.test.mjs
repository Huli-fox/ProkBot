import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createSelfHostServer } from '../server/index.mjs';

test('management reports effective capabilities while preserving preferences and rejecting native browser bridges in MCP-only mode', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'prokbot-external-http-'));
  const before = process.env.GROKBOT_BOX_DISABLED;
  let app, computers = [];
  try {
    process.env.GROKBOT_BOX_DISABLED = '1';
    app = await createSelfHostServer({ dataDir: directory, modelFile: join(directory, 'model.env'),
      internalToken: 'external_box_test_internal_token_0000000000', computers: () => ({ available: true, computers }) });
    const { port } = await app.start(0, '127.0.0.1');
    const base = `http://127.0.0.1:${port}`, password = 'external-box-http-test-password';
    await app.auth.setup(app.auth.setupKey, password);
    const login = await fetch(`${base}/admin/api/login`, { method: 'POST', headers: { origin: base,
      'content-type': 'application/json', 'x-grokbot-csrf': '1' }, body: JSON.stringify({ password }) });
    assert.equal(login.status, 200);
    const headers = { cookie: login.headers.get('set-cookie').split(';')[0], origin: base,
      'content-type': 'application/json', 'x-grokbot-csrf': '1' };
    const status = async () => {
      const response = await fetch(`${base}/admin/api/harness`, { headers });
      assert.equal(response.status, 200); return response.json();
    };
    const initial = await status();
    assert.equal(initial.userForm, true);
    assert.equal(initial.effective.userForm, false);
    assert.equal(initial.effective.macComputer, false);
    assert.equal(initial.executionMode, 'remote-mcp');
    computers = [{ id: 'offline-mac', connected: false }];
    assert.equal((await status()).effective.macComputer, false);
    computers.push({ id: 'online-mac', connected: true });
    assert.equal((await status()).effective.macComputer, true);
    assert.equal((await status()).effective.passkeys, false);
    const saved = await fetch(`${base}/admin/api/harness`, { method: 'PUT', headers,
      body: JSON.stringify({ ...initial, userForm: false }) });
    assert.equal(saved.status, 200);
    assert.equal((await saved.json()).userForm, false);
    assert.equal(app.harness.current().browserUse, true);
    assert.equal(app.harness.current().userForm, false);
    const { pairingKey } = await app.auth.createPairing();
    const paired = await fetch(`${base}/connect/pair`, { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pairingKey, platform: 'desktop', deviceName: 'Test desktop' }) });
    assert.equal(paired.status, 201);
    const { token } = await paired.json();
    for (const channel of ['cookie-origin-approval', 'webauthn']) {
      const response = await fetch(`${base}/${channel}/requests`, { headers: { authorization: `Bearer ${token}` } });
      assert.equal(response.status, 409);
      await response.body.cancel();
    }
  } finally {
    await app?.close();
    if (before === undefined) delete process.env.GROKBOT_BOX_DISABLED; else process.env.GROKBOT_BOX_DISABLED = before;
    await rm(directory, { recursive: true, force: true });
  }
});

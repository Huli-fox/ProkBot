import test from 'node:test';
import assert from 'node:assert/strict';
import { Auth } from '../server/auth.mjs';
import { PushService } from '../server/push-service.mjs';

// Authentication and push policy tests do not require filesystem persistence or a model service.
function memoryStore(store) {
  store.mutate = async update => {
    const next = structuredClone(store.value);
    const result = await update(next);
    store.value = next;
    return result;
  };
  return store;
}
function auth() {
  const value = new Auth('/unused-in-this-test');
  memoryStore(value.store);
  value.store.value = structuredClone(value.store.initial);
  return value;
}

test('Android pairing issues a device token, consumes the code, and respects revocation', async () => {
  const service = auth();
  const { pairingKey } = await service.createPairing();
  const paired = await service.pair({ pairingKey, deviceName: ' Android phone ', platform: 'android' });
  assert.equal(service.authenticate(paired.token)?.platform, 'android');
  assert.equal(service.authenticate(paired.token)?.name, 'Android phone');
  assert.equal(JSON.stringify(service.store.value).includes(paired.token), false);
  await assert.rejects(service.pair({ pairingKey, deviceName: 'Second phone', platform: 'android' }), { status: 401 });
  await service.revoke(paired.deviceId);
  assert.equal(service.authenticate(paired.token), null);
});

test('unknown platforms and expired codes cannot consume a usable pairing code', async () => {
  const service = auth();
  const { pairingKey } = await service.createPairing();
  await assert.rejects(service.pair({ pairingKey, deviceName: 'Phone', platform: 'unknown' }), { status: 400 });
  assert.equal(service.pairingKeys().length, 1);
  service.store.value.pairing[0].expiresAt = 0;
  await assert.rejects(service.pair({ pairingKey, deviceName: 'Phone', platform: 'android' }), { status: 401 });
});

test('Android has its own device kind and does not acquire APNs capabilities', async () => {
  const service = auth();
  const { pairingKey } = await service.createPairing();
  const { deviceId } = await service.pair({ pairingKey, deviceName: 'Phone', platform: 'android' });
  const push = new PushService('/unused-in-this-test', service);
  memoryStore(push.store);
  push.store.value = structuredClone(push.store.initial);
  assert.equal(push.get(deviceId).kind, 'android');
  const registered = await push.register(deviceId, { kind: 'android', bundleId: 'ai.x.grok.bot', appVersion: '1.19.1', push: { provider: 'none' } });
  assert.equal(registered.kind, 'android');
  assert.equal(registered.push.provider, 'none');
  assert.equal(registered.push.capable, false);
  await assert.rejects(push.register(deviceId, { push: { provider: 'apns', token: 'a'.repeat(64) } }), { status: 400 });
  assert.equal(push.get(deviceId).push.provider, 'none');
});

test('desktop and iOS pairing and default device kinds retain their behavior', async () => {
  const service = auth();
  const push = new PushService('/unused-in-this-test', service);
  push.store.value = structuredClone(push.store.initial);
  for (const [platform, kind] of [['desktop', 'mac'], ['ios', 'iphone']]) {
    const { pairingKey } = await service.createPairing();
    const { deviceId, token } = await service.pair({ pairingKey, deviceName: platform, platform });
    assert.equal(service.authenticate(token).platform, platform);
    assert.equal(push.get(deviceId).kind, kind);
  }
});

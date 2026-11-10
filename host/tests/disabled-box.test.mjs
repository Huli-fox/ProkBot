import test from 'node:test';
import assert from 'node:assert/strict';
import { createDisabledBox, createDisabledBoxMcpExec, withoutBoxSkills } from '../runtime/disabled-box.mjs';
import { installRemoteBoxAdapter } from '../runtime/remote-box.mjs';
import { withLocalLibraryRunner } from '../runtime/host-library-files.mjs';

test('disabled Box cannot expose native execution or files even with a configured hostname', async () => {
  const bindings = {};
  assert.deepEqual(installRemoteBoxAdapter(bindings, {}, { GROKBOT_BOX_DISABLED: '1', GROKBOT_BOX_HOST: 'box' }), { mode: 'disabled' });
  const box = bindings.createSandBox();
  assert.equal(await box.isAvailable(), false);
  assert.deepEqual(await box.listBoxes(), []);
  for (const method of ['ensureReady', 'ensureWindow', 'applyEnvironment', 'loadMcpServers', 'mcpResourceAccessor', 'uploadFile', 'downloadFile']) {
    await assert.rejects(box[method](), { code: 'GROKBOT_BOX_DISABLED' });
  }
  await box.dispose();
});

test('remote MCP startup can discover an empty local registry; local stdio still fails clearly', async () => {
  const exec = createDisabledBoxMcpExec();
  assert.deepEqual(await exec.listTools([]), []);
  await exec.loadServers('{"mcpServers":{}}');
  await assert.rejects(exec.loadServers('{"mcpServers":{"local":{"command":"node"}}}'), { code: 'GROKBOT_BOX_DISABLED' });
  assert.equal((await exec.listTools(['local']))[0].status, 'error');
  await assert.rejects(exec.executeTool(), { code: 'GROKBOT_BOX_DISABLED' });
});

test('default deployment still selects the original Box adapter', () => {
  const bindings = { createSandBox: () => 'original' };
  assert.deepEqual(installRemoteBoxAdapter(bindings, {}, {}), { mode: 'in-container' });
  assert.equal(bindings.createSandBox(), 'original');
});

test('text turns omit native capabilities and skill/file synchronization; attachments fail explicitly', async () => {
  const previous = { data: process.env.GROKBOT_DATA_DIR, disabled: process.env.GROKBOT_BOX_DISABLED };
  process.env.GROKBOT_DATA_DIR = '/unused-in-this-test';
  process.env.GROKBOT_BOX_DISABLED = '1';
  try {
    class Runner {
      constructor(options) { this.options = options; }
      async run() { return this.options.requestContext.resolveRules(); }
      setSkillStore(store) { this.skillStore = store; }
    }
    const store = { list: () => ['requires Box file reads'], label: 'test', name() { return this.label; } };
    const Wrapped = withLocalLibraryRunner(Runner, {});
    const runner = new Wrapped({ remoteBox: createDisabledBox(), skillStore: store,
      remoteBoxHasDesktop: true, getRemoteBoxAvailable: () => true,
      requestContext: { resolveRules: async () => ['profile rules'] } });
    assert.equal(runner.options.remoteBoxHasDesktop, false);
    assert.equal(runner.options.getRemoteBoxAvailable(), false);
    assert.deepEqual(await runner.run('hello'), ['profile rules']);
    assert.deepEqual(runner.options.skillStore.list(), []);
    assert.equal(withoutBoxSkills(store).name(), 'test');
    runner.setSkillStore(store);
    assert.deepEqual(runner.skillStore.list(), []);
    await assert.rejects(runner.run('read file', { attachedFilePaths: ['/file'] }), { code: 'GROKBOT_BOX_DISABLED' });
    assert.deepEqual(store.list(), ['requires Box file reads']);
  } finally {
    for (const [name, value] of [['GROKBOT_DATA_DIR', previous.data], ['GROKBOT_BOX_DISABLED', previous.disabled]]) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
  }
});

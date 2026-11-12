import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { executionRunnerOptions } from '../runtime/execution-capabilities.mjs';
import { defaultHarnessSettings, harnessCapabilityStatus } from '../server/harness-settings.mjs';
import { createLocalCapabilities } from '../runtime/host-capabilities.mjs';
import { executionPromptBindings, executionPromptDependencies } from '../runtime/execution-prompt-runtime.mjs';
import { externalPromptSections, externalPromptEdits } from '../runtime/execution-prompt.mjs';
import { installLocalPromptPolicy } from '../runtime/prompt-runtime.mjs';
import { promptId } from '../server/prompt-settings.mjs';

test('native tools require live execution providers and follow connect/disconnect without rebuilding the runner', () => {
  let computers = [];
  const options = { remoteBoxHasDesktop: true, getRemoteBoxAvailable: () => true,
    userComputers: { list: () => computers },
    gates: { browserUseSubagent: () => true, userForm: () => true, agentPromptedCookieSync: () => true, messagesTools: () => true } };
  const native = executionRunnerOptions(options, { disabled: false });
  const external = executionRunnerOptions(options, { disabled: true });
  assert.equal(native.hasUserComputer(), false);
  assert.equal(native.gates.agentPromptedCookieSync(), false);
  assert.equal(native.gates.userForm(), true);
  computers = [{ id: 'mac-offline', connected: false }];
  assert.equal(native.hasUserComputer(), false);
  computers.push({ id: 'mac-live', connected: true });
  assert.equal(native.hasUserComputer(), true);
  assert.equal(native.gates.agentPromptedCookieSync(), true);
  assert.equal(external.hasUserComputer(), true, 'MCP-only still supports an independently connected desktop');
  for (const key of ['browserUseSubagent', 'userForm', 'agentPromptedCookieSync']) assert.equal(external.gates[key](), false);
  assert.equal(external.getRemoteBoxAvailable(), false);
  computers = [];
  assert.equal(external.hasUserComputer(), false);
  assert.equal(native.gates.messagesTools(), false);
  assert.equal(executionRunnerOptions({ hasUserComputer: () => true }, { disabled: false }).hasUserComputer(), false);
  assert.equal(executionRunnerOptions({ ...options, hasUserComputer: () => false }, { disabled: false }).hasUserComputer(), false);
});

test('capability status preserves saved preferences and reports the effective mode', () => {
  const external = harnessCapabilityStatus(defaultHarnessSettings, { nativeBox: false, userComputer: false });
  assert.equal(external.browserUse, true);
  assert.equal(external.effective.browserUse, false);
  assert.equal(external.effective.userForm, false);
  assert.equal(external.effective.macComputer, false);
  assert.equal(external.executionMode, 'remote-mcp');
  const withMac = harnessCapabilityStatus(defaultHarnessSettings, { nativeBox: false, userComputer: true });
  assert.equal(withMac.effective.macComputer, true);
  assert.equal(withMac.effective.browserLoginImport, false);
  const native = harnessCapabilityStatus(defaultHarnessSettings, { nativeBox: true, userComputer: true });
  assert.deepEqual(native.effective, defaultHarnessSettings);
  const disabled = harnessCapabilityStatus({ ...defaultHarnessSettings, userForm: false }, { nativeBox: true, userComputer: true });
  assert.equal(disabled.effective.userForm, false);
});

test('external mode gates native services even when an old settings file has them enabled', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'prokbot-external-capabilities-'));
  const before = process.env.GROKBOT_BOX_DISABLED;
  let capabilities;
  try {
    process.env.GROKBOT_BOX_DISABLED = '1';
    capabilities = await createLocalCapabilities(directory);
    const experiments = capabilities.experiments({ checkFeatureGate: () => true });
    for (const gate of ['sand_browser_use_subagent', 'sand_user_form', 'agent_prompted_cookie_sync', 'sand_teach_by_demonstration'])
      assert.equal(experiments.checkFeatureGate(gate), false);
    assert.equal(experiments.checkFeatureGate('sand_share_bot'), true);
    assert.equal(experiments.checkFeatureGate('other-existing-feature'), true);
    assert.deepEqual(capabilities.get(), defaultHarnessSettings);
  } finally {
    capabilities?.close();
    if (before === undefined) delete process.env.GROKBOT_BOX_DISABLED; else process.env.GROKBOT_BOX_DISABLED = before;
    await rm(directory, { recursive: true, force: true });
  }
});

test('section adaptation does not rewrite arbitrary instructions and leaves native sections intact', () => {
  const safety = { heading: '## Security', body: ['Keep user approvals. A user path /home/box is source data.'] };
  const sections = [safety, { heading: '## Where you work', body: ['native environment'] }];
  assert.equal(externalPromptSections(sections, false), sections);
  const external = externalPromptSections(sections, true);
  assert.equal(external[0], safety);
  assert.match(external[1].body.join('\n'), /Simular and InstaBox/);
  assert.match(external[1].body.join('\n'), /Do not silently switch providers/);
  assert.doesNotMatch(external[1].body.join('\n'), /Shell starts in/);
  const edits = new Map([['## Tone', { kind: 'replace', body: ['tone'] }]]);
  assert.equal(externalPromptEdits(edits, false), edits);
  assert.equal(externalPromptEdits(edits, true).get('## Tone'), edits.get('## Tone'));
});

test('old native memory snapshots are rendered again without changing stored facts', () => {
  const facts = { profile: [{ text: 'My project uses /home/box/reference' }], recent: [] };
  const original = {
    renderMemorySystemPrompt: (recall, location) => `facts: ${JSON.stringify(recall)}; location: ${location}`,
    resolveFrozenMemoryPrompt: ({ snapshot, renderLive }) => snapshot ?? renderLive(),
  };
  const adapted = executionPromptDependencies(original, true);
  const rendered = adapted.renderMemorySystemPrompt(facts, '/home/box/memory');
  assert.match(rendered, /My project uses \/home\/box\/reference/);
  assert.match(rendered, /location: null/);
  assert.match(rendered, /update_state/);
  const snapshot = { render: 'Your memory lives in a folder at /home/box/memory\nfacts unchanged', compactionEpoch: 1 };
  const refreshed = adapted.resolveFrozenMemoryPrompt({ snapshot, renderLive: () => ({ render: rendered }) });
  assert.equal(refreshed.render, rendered);
  assert.match(snapshot.render, /Your memory lives/);
  assert.equal(adapted.resolveFrozenMemoryPrompt({ snapshot: refreshed, renderLive: () => assert.fail('already adapted') }), refreshed);
  assert.equal(executionPromptDependencies(original, false), original);
});

test('dynamic adaptation retains custom bases, metadata, and generator observation hooks', () => {
  const hook = () => {};
  let received;
  const originals = { createSystemPromptAssembly: deps => {
    received = deps;
    return { getSystemPrompt: snapshot => snapshot,
      createSystemPromptGeneratorForRun: snapshot => Object.assign(() => snapshot, { localObserveTools: hook }) };
  } };
  const adapted = executionPromptBindings({}, originals, true);
  const profile = { name: 'Bot', description: 'Project /home/box is a fact.', filePath: '/host/profile', settingsFilePath: '/host/settings' };
  const deps = { basePrompt: 'my custom base /workspace', agentProfileProvider: () => () => profile };
  const assembly = adapted.createSystemPromptAssembly(deps);
  assert.equal(received.basePrompt, deps.basePrompt);
  assert.equal(received.agentProfileProvider()().description, profile.description);
  assert.equal(received.agentProfileProvider()().filePath, '');
  assert.equal(profile.filePath, '/host/profile');
  assert.equal(received.skillStore(), null);
  assert.equal(received.isUserFormEnabled(), false);
  assert.match(received.remoteBoxSection(), /External execution environment/);
  assert.equal(received.computerSection(), null);
  const snapshot = { profileSection: 'Description: Project /home/box is a fact.\nYour profile is a JSON config file at /host/profile which you can read' };
  const generator = assembly.createSystemPromptGeneratorForRun(snapshot);
  assert.equal(generator.localObserveTools, hook);
  assert.equal(generator().profileSection, 'Description: Project /home/box is a fact.');
  assert.match(snapshot.profileSection, /JSON config/);
  assert.equal(executionPromptBindings({}, originals, false), originals);
});

test('prompt edits remain frozen for a running turn and survive external runtime observation', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'prokbot-external-prompts-'));
  const original = 'External default prompt', id = promptId('parent', original);
  let policy;
  try {
    await writeFile(join(directory, 'prompt-settings.json'), JSON.stringify({ version: 1,
      entries: { [id]: { revisions: [{ number: 1, content: 'User custom instructions /workspace' }] } } }));
    policy = await installLocalPromptPolicy(directory, null);
    const turn = policy.snapshot();
    assert.equal(turn('parent', original), 'User custom instructions /workspace');
    turn.recordTools([{ name: 'GetMcpTools' }]);
    turn.recordAssembly({ base: turn('parent', original), sections: ['Execution computer'] });
    await writeFile(join(directory, 'prompt-settings.json'), JSON.stringify({ version: 1, entries: {} }));
    await policy.refresh();
    assert.equal(turn('parent', original), 'User custom instructions /workspace');
    assert.equal(policy.snapshot()('parent', original), original);
  } finally { await policy?.close(); await rm(directory, { recursive: true, force: true }); }
});

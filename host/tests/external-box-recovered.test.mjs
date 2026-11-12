import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { executionRunnerOptions } from '../runtime/execution-capabilities.mjs';
import { executionPromptBindings, executionPromptDependencies } from '../runtime/execution-prompt-runtime.mjs';

// Generated upstream code is deliberately not checked in. Run against patch-host.py's output.
const seed = process.env.GROKBOT_TEST_RECOVERED_DIR;
const fixture = { skip: !seed && 'Set GROKBOT_TEST_RECOVERED_DIR to the prepared release-reliability directory' };
async function recovered(name) {
  let source = await readFile(resolve(seed, name), 'utf8');
  const required = JSON.parse(source.match(/(?:for \(const name of |const required = )(\[[^\n]+?\])/)[1]);
  source = source.replace(/file:\/\/\/opt\/grokbot\/runtime\/[^"']+/g, path =>
    new URL(path.slice('file:///opt/grokbot/'.length), new URL('../', import.meta.url)).href);
  source += `\n//# sourceURL=prepared-${name}\n`;
  const module = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  return { create: module.createRecoveredModule, required };
}

const off = () => false;
function promptInputs() {
  return { GROUP_CHAT_TAG_PREFIX: '[group]', GROUP_MAX_MESSAGES_PER_TURN: 20,
    SAND_APP_UI_REFERENCE_PATH: '/home/box/reference/app-ui.md',
    SAND_BOX_DEBUGGING_REFERENCE_PATH: '/home/box/reference/debugging-the-box.md',
    SAND_VOICE_CALL_PROMPT_SECTION: '', isOffRecordMessageId: off,
    normalizeSubagentTypeName: value => value.toLowerCase(),
    sandMcpMetaToolNames: dynamic => dynamic ? { discovery: 'tool_search', invocation: 'mcp_call' }
      : { discovery: 'GetMcpTools', invocation: 'CallMcpTool' } };
}
async function promptBindings() {
  const inputs = promptInputs();
  const base = (await recovered('prompt-tools-system-prompt.mjs')).create(inputs);
  const slim = (await recovered('prompt-tools-slim-system-prompt.mjs')).create({ ...inputs, ...base,
    buildSandSettingsDeepLinkUrl: section => `grokbot://settings/${section}` });
  return { ...base, ...slim, ...inputs };
}
const options = { cloudAgentsEnabled: false, dynamicToolsEnabled: false, multiMachineLocalExecEnabled: false,
  voiceCallEnabled: false, hostSurfaces: { userComputer: false } };

test('real standard, slim, and automation prompt factories support external MCP and retain native mode', fixture, async () => {
  const before = process.env.GROKBOT_BOX_DISABLED;
  try {
    process.env.GROKBOT_BOX_DISABLED = '1';
    const bindings = await promptBindings();
    for (const [name, generate] of Object.entries({ parent: bindings.sandBaseSystemPromptVariant,
      slim: bindings.slimSandBaseSystemPromptVariant, automation: bindings.sandAutomationSubagentSystemPromptVariant })) {
      for (const dynamicToolsEnabled of [false, true]) {
        const prompt = generate({ ...options, dynamicToolsEnabled });
        assert.match(prompt, /Simular and InstaBox/, name);
        assert.match(prompt, /No Mac is required/, name);
        assert.doesNotMatch(prompt, /\/home\/box|\/workspace|file:\/\/\/workspace/, name);
        assert.doesNotMatch(prompt, /each agent gets its own screen|box-chrome|app copies it|must be connected or Codex/, name);
        assert.match(prompt, /Auto-review|automatic.*review/i, name);
        if (name === 'automation') {
          assert.match(prompt, /WakeParent/);
          assert.match(prompt, /Stay quiet by default/);
          assert.doesNotMatch(prompt, /## SendToUser is your only voice/);
        } else assert.match(prompt, /SendToUser is your only voice/);
      }
    }
    const general = bindings.buildSandSubagentSystemPrompt({ subagentType: 'generalPurpose', readonly: true });
    assert.match(general, /readonly mode/);
    assert.match(general, /final assistant message/);
    delete process.env.GROKBOT_BOX_DISABLED;
    const native = await promptBindings();
    assert.match(native.sandBaseSystemPromptVariant(options), /\/workspace/);
    assert.match(native.slimSandBaseSystemPromptVariant(options), /\/home\/box/);
    assert.match(native.sandAutomationSubagentSystemPromptVariant(options), /WakeParent/);
  } finally {
    if (before === undefined) delete process.env.GROKBOT_BOX_DISABLED; else process.env.GROKBOT_BOX_DISABLED = before;
  }
});

test('real assembly removes native dynamic sections for main, general, and automation roles', fixture, async () => {
  const before = process.env.GROKBOT_BOX_DISABLED;
  try {
    process.env.GROKBOT_BOX_DISABLED = '1';
    const bindings = await promptBindings();
    const module = await recovered('prompt-tools-system-prompt-assembly.mjs');
    const inputs = Object.fromEntries(module.required.map(name => [name, () => '']));
    Object.assign(inputs, bindings, { isMemoryFreezeEnabled: off, renderTimeZoneSystemPrompt: () => 'timezone retained',
      renderUserIdentitySystemPrompt: () => 'user identity retained' });
    const { createSystemPromptAssembly } = executionPromptBindings({}, module.create(executionPromptDependencies(inputs, true)), true);
    for (const role of ['parent', 'generalPurpose', 'automation']) {
      const gates = new Proxy({}, { get: (_, key) => () => key === 'cloudAgentsDisabledByTeam' });
      const deps = { basePrompt: role === 'generalPurpose' ? bindings.buildSandSubagentSystemPrompt({ subagentType: role }) : bindings.SAND_SYSTEM_PROMPT_CLOUD_AGENTS_DISABLED,
        localPromptRole: role, isSubagentRunner: role !== 'parent', isParentMediatedAutomationSubagent: role === 'automation',
        isSystemPromptOverridden: role === 'generalPurpose', isBoxScopedSubagent: off, hasUserComputer: off,
        gates, connectorManifests: [], requestContext: { resolve: () => ({}) },
        agentProfileProvider: () => () => ({ name: 'Keep Bot', description: 'Keep user description', filePath: '/home/box/profile.json', settingsFilePath: '/home/box/settings.json' }),
        agentStore: () => null, memoryStore: () => null, userMemory: () => null, projectMemory: () => null,
        automationStore: () => null, skillStore: () => ({ getLocation: () => '/home/box/skills' }),
        channelStore: () => null, mcpManagement: () => null, isUserFormEnabled: () => true,
        mcpCustomInstructionsSection: () => 'Preserve user MCP instructions: /workspace is my project path',
        mcpDiscoveryStatusSection: () => 'Provider discovery is temporarily unavailable',
        remoteBoxSection: () => '## Your box\nNative computer exists', computerSection: () => 'Native desktop exists' };
      const assembly = createSystemPromptAssembly(deps);
      const prompt = assembly.createSystemPromptGeneratorForRun()();
      assert.match(prompt, /External execution environment/, role);
      assert.match(prompt, /Provider discovery is temporarily unavailable/, role);
      assert.match(prompt, /Preserve user MCP instructions: \/workspace is my project path/, role);
      assert.match(prompt, /Keep user description/, role);
      assert.doesNotMatch(prompt, /## Your box|Native desktop exists|\/home\/box\/skills|\/home\/box\/profile/, role);
      assert.doesNotMatch(prompt, /User form|request_user_form/, role);
      if (role === 'automation') assert.match(prompt, /WakeParent/);
    }
  } finally {
    if (before === undefined) delete process.env.GROKBOT_BOX_DISABLED; else process.env.GROKBOT_BOX_DISABLED = before;
  }
});

test('real tool builder retains MCP discovery and hides absent native and user-computer tools', fixture, async () => {
  const module = await recovered('prompt-tools-turn-toolset.mjs');
  const names = { createSendMessageTool2: 'SendToUser', createReactToMessageTool: 'ReactToMessage',
    createGetMcpToolsTool: 'GetMcpTools', createCallMcpTool: 'CallMcpTool', createRequestCookieOriginApprovalTool: 'request_cookie_origin_approval',
    createRequestUserFormTool: 'request_user_form', createScreenshotTool: 'Screenshot', createRequestBoxHelpTool: 'request_box_help',
    createAwaitTool: 'AwaitExternalShell' };
  const inputs = Object.fromEntries(module.required.map(name => [name, () => undefined]));
  for (const [factory, name] of Object.entries(names)) inputs[factory] = () => ({ name, execute() {} });
  Object.assign(inputs, { AgentType: { IDE: 'ide' }, resolveSandExternalMachine: () => ({}),
    SAND_EXTERNAL_SHELL_TOOL_NAME: 'ExternalShell', SAND_EXTERNAL_READ_TOOL_NAME: 'ExternalRead',
    SAND_EXTERNAL_AWAIT_SHELL_TOOL_NAME: 'AwaitExternalShell', SAND_BOX_SHELL_TOOL_NAME: 'Shell', SAND_BOX_READ_TOOL_NAME: 'Read', SAND_BOX_AWAIT_SHELL_TOOL_NAME: 'AwaitShell',
    createShellTool: (_resources, args) => ({ name: args.toolName, execute() {} }),
    createReadTool: (_resources, _format, _version, args) => ({ name: args.toolName, execute() {} }),
    createToolHandoff: () => ({ wrapTool: tool => tool }),
    wrapToolWithTimeout: tool => tool, fencedToolSet: tools => tools,
    sandMcpMetaToolNames: promptInputs().sandMcpMetaToolNames,
  });
  const { buildTurnTools } = module.create(inputs);
  let computers = [];
  const source = { userComputers: { list: () => computers }, remoteBoxHasDesktop: true, getRemoteBoxAvailable: () => true,
    gates: new Proxy({}, { get: () => off }) };
  const external = executionRunnerOptions(source, { disabled: true });
  const host = { ...external, isSubagentRunner: false, isBoxScopedSubagent: false,
    gates: new Proxy(external.gates, { get: (target, key) => target[key] ?? off }),
    mcp: {}, getConversationId: () => 'test-bot', getShellApprovalState: () => ({}),
    createFileTransferController: () => ({ userComputers: source.userComputers }) };
  const turn = { config: { systemPromptGenerator: () => '' }, boxConnection: {},
    autoReviewModes: {}, getAutoReviewUserInstructions: () => '', multiMachineLocalExecEnabled: false };
  const tools = () => buildTurnTools(host, turn, { mcpTools: [
    { providerIdentifier: 'simular-box', name: 'simular-box-exec' },
    { providerIdentifier: 'instabox', name: 'instabox-exec' },
  ] }).map(tool => tool.name);
  assert.deepEqual(tools(), ['SendToUser', 'ReactToMessage', 'GetMcpTools', 'CallMcpTool']);
  computers = [{ id: 'mac-live', connected: true }];
  assert.ok(tools().includes('ExternalShell'));
  assert.ok(tools().includes('ExternalRead'));
  assert.ok(!tools().includes('Shell'));
  assert.ok(!tools().includes('request_cookie_origin_approval'));
  computers = [];
  assert.ok(!tools().includes('ExternalShell'));
  host.isSubagentRunner = true;
  assert.deepEqual(tools(), ['GetMcpTools', 'CallMcpTool']);
});

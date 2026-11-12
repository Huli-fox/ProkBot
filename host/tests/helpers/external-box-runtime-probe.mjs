import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { cp, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { prepareHostReliability } from '../../runtime/reliability/prepare.mjs';
import { loadRecoveredHostCore } from '../../runtime/recovered-host-core.mjs';
import { executionPromptDependencies } from '../../runtime/execution-prompt-runtime.mjs';
import { installLocalPromptPolicy } from '../../runtime/prompt-runtime.mjs';

const state = await mkdtemp(join(tmpdir(), 'prokbot-runtime-probe-'));
Object.assign(process.env, { GROKBOT_DATA_DIR: state, GROKBOT_STATE_DIR: state, SAND_DATA_ROOT: join(state, 'host-data') });
const external = process.env.GROKBOT_BOX_DISABLED === '1';
let prompts;
try {
  await mkdir(process.env.SAND_DATA_ROOT);
  const seed = resolve(process.env.GROKBOT_TEST_RECOVERED_DIR, '..');
  for (const entry of ['blob-worker-library-provenance.json', 'blob-worker-library.cjs', 'recovered-core', 'recovered-worker'])
    await cp(join(seed, entry), join(state, entry), { recursive: true });
  const prepared = await prepareHostReliability(state);
  const library = createRequire(import.meta.url)(prepared.libraryPath);
  const core = await loadRecoveredHostCore(library, prepared.directory);
  assert.equal(core.computer.deployment.mode, external ? 'disabled' : 'in-container');
  assert.equal(core.promptTools.installed, true);
  assert.equal(core.harness.installed, true);
  const bindings = library.getPromptToolsRecoveryBindings();
  const prompt = bindings.sandBaseSystemPromptVariant({ cloudAgentsEnabled: false, hostSurfaces: { userComputer: false } });
  if (external) {
    assert.match(prompt, /Simular and InstaBox/);
    assert.doesNotMatch(prompt, /\/home\/box|\/workspace/);
    const renderers = executionPromptDependencies(bindings, true);
    const fact = { content: 'Keep /home/box in my project notes', createdAt: Date.now(), tier: 'profile', via: 'Test Bot' };
    for (const [name, args] of [
      ['renderMemorySystemPrompt', [{ profile: [fact], recent: [] }, '/home/box/memory']],
      ['renderUserMemorySystemPrompt', [{ profile: [fact], recent: [] }, { userMemoryDir: '/home/box/user-memory', ownShardDir: '/home/box/shard' }]],
      ['renderProjectMemorySystemPrompt', [{ injected: [{ name: 'Test', slug: 'test', ownShardDir: '/home/box/project', recall: { profile: [fact], recent: [] } }], alsoMemberOf: [] }, { projectsRootDir: '/home/box/projects' }]],
    ]) {
      const rendered = renderers[name](...args);
      assert.match(rendered, /Keep \/home\/box in my project notes/, name);
      assert.doesNotMatch(rendered, /Read and Shell|grep.*folder|\/home\/box\/memory|\/home\/box\/user-memory|\/home\/box\/projects/, name);
      assert.match(rendered, /update_state/, name);
    }
    const routines = renderers.renderAutomationsSystemPrompt([], '/home/box/routines', 'Asia/Shanghai', {});
    assert.doesNotMatch(routines, /\/home\/box\/routines/);
    assert.match(routines, /update_state/);
  } else assert.match(prompt, /\/workspace/);
  prompts = await installLocalPromptPolicy(state, library);
  await prompts.flush();
  console.log(JSON.stringify({ mode: external ? 'external-mcp' : 'native-box', recoveredModules: core.modules.length,
    promptModules: core.promptTools.modules.length, promptCatalog: 'ok', modelCalls: 0, remoteMcpCalls: 0 }));
} finally { await prompts?.close(); await rm(state, { recursive: true, force: true }); }

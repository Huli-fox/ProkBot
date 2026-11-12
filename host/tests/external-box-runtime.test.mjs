import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const skip = process.env.GROKBOT_TEST_FULL_RUNTIME !== '1' && 'Requires the prepared Linux Host image and generated seed';
for (const mode of ['0', '1']) test(`full recovered runtime installs with GROKBOT_BOX_DISABLED=${mode}`, { skip }, () => {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL('helpers/external-box-runtime-probe.mjs', import.meta.url))], {
    env: { ...process.env, GROKBOT_BOX_DISABLED: mode }, encoding: 'utf8', timeout: 60000,
  });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.match(result.stdout, /"promptCatalog":"ok"/);
});

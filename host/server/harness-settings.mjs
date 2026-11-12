import { join } from 'node:path';
import { JsonStore } from './storage.mjs';
import { check } from './security.mjs';
import { boxDisabled } from '../runtime/disabled-box.mjs';

export const defaultHarnessSettings = Object.freeze({ dreaming: false, browserUse: true, userForm: true,
  browserLoginImport: true, passkeys: true, macComputer: true, teachTask: true });

/** Keep preferences intact so reconnecting a device or enabling a native Box restores them. */
export function harnessCapabilityStatus(settings, { nativeBox = !boxDisabled(), userComputer = false } = {}) {
  const unavailable = {};
  if (!nativeBox) for (const key of ['browserUse', 'userForm', 'browserLoginImport', 'passkeys', 'teachTask'])
    unavailable[key] = '需要原生执行 Box；外接 MCP 不使用此开关';
  if (!userComputer) for (const key of ['browserLoginImport', 'passkeys', 'macComputer'])
    unavailable[key] ??= '等待桌面客户端连接';
  const effective = Object.fromEntries(Object.entries(settings).map(([key, enabled]) => [key, enabled && !unavailable[key]]));
  return { ...settings, effective, unavailable, executionMode: nativeBox ? 'native-box' : 'remote-mcp' };
}
export function validateHarnessSettings(input) {
  const next = {};
  for (const [key, fallback] of Object.entries(defaultHarnessSettings)) {
    check(input[key] === undefined || typeof input[key] === 'boolean', 400, `Invalid ${key}`);
    next[key] = input[key] ?? fallback;
  }
  return next;
}
export class HarnessSettings {
  constructor(directory) { this.store = new JsonStore(join(directory, 'harness-settings.json'),
    { version: 1, settings: { ...defaultHarnessSettings } }); }
  async load() { await this.store.load(); return this; }
  current() { return validateHarnessSettings(this.store.value.settings); }
  status(availability) { return harnessCapabilityStatus(this.current(), availability); }
  async save(input) {
    const settings = validateHarnessSettings(input);
    await this.store.mutate(state => { state.settings = settings; });
    return this.current();
  }
}

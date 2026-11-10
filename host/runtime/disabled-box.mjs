export const boxDisabled = (env = process.env) => env.GROKBOT_BOX_DISABLED === '1';

export function boxDisabledError() {
  const error = new Error('The built-in execution Box is disabled. Use an authorized remote MCP application.');
  error.code = 'GROKBOT_BOX_DISABLED';
  return error;
}

const unavailable = async () => { throw boxDisabledError(); };

/** Explicit absence of a native execution node; never fall back to the Host filesystem. */
export function createDisabledBox() {
  return {
    describe: () => ({ backend: 'disabled' }),
    isAvailable: async () => false,
    isPreparing: () => false,
    runState: async () => 'stopped',
    listBoxes: async () => [],
    maxWindows: () => 1,
    getTerminalsFolder: () => undefined,
    setTelemetry() {},
    ensureReady: unavailable,
    ensureWindow: unavailable,
    applyEnvironment: unavailable,
    loadMcpServers: unavailable,
    mcpResourceAccessor: unavailable,
    uploadFile: unavailable,
    downloadFile: unavailable,
    async releaseWindow() {},
    async hibernate() {},
    async dispose() {},
  };
}

/** Empty local discovery is valid while remote HTTP MCP remains available. */
export function createDisabledBoxMcpExec() {
  return {
    async loadServers(configJson) {
      if (Object.keys(JSON.parse(configJson).mcpServers ?? {}).length) throw boxDisabledError();
    },
    async listTools(identifiers) {
      return identifiers.map(serverIdentifier => ({ serverIdentifier, status: 'error',
        statusDetail: boxDisabledError().message, toolCount: 0, tools: [] }));
    },
    executeTool: unavailable,
  };
}

export function withoutBoxSkills(store) {
  if (!store) return store;
  return new Proxy(store, { get(target, key) {
    if (key === 'list') return () => [];
    const value = Reflect.get(target, key);
    return typeof value === 'function' ? value.bind(target) : value;
  } });
}

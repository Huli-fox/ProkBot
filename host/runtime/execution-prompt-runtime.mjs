import { boxDisabled } from './disabled-box.mjs';
import { externalExecutionSection } from './execution-prompt.mjs';

const memoryEditGuidance = 'Host-managed memory is separate from external machines. Use update_state target "memory", action "write" or "forget", with the appropriate scope and tier; only the facts included here are available for recall.';

// These are generated budget notices, not memory facts (which have their own prefixes).
const omitDiskLookup = text => text.replace(/^\((\d+ more [^\n]*?)\s+(?:on disk )?— grep [^\n]*\)$/gm, '($1 not shown.)');

/** Preserve the original data rendering and budgets while replacing only generated storage instructions. */
export function executionPromptDependencies(original, disabled = boxDisabled()) {
  if (!disabled) return original;
  const adapted = { ...original };
  const wrap = (name, render) => {
    if (typeof original[name] === 'function') adapted[name] = (...args) => render(original[name], ...args);
  };
  wrap('renderMemorySystemPrompt', (render, recall) =>
    [render(recall, null), memoryEditGuidance].filter(Boolean).join('\n'));
  wrap('renderUserMemorySystemPrompt', (render, recall, context) => {
    const text = render(recall, { ...context, ownShardDir: null });
    return text ? `${omitDiskLookup(text)}\n${memoryEditGuidance} For shared user facts use scope "user"; write corrections to your own shard.` : text;
  });
  wrap('renderProjectMemorySystemPrompt', (render, recall, context) => {
    const text = render({ ...recall, injected: recall.injected.map(block => ({ ...block, ownShardDir: null })) }, context);
    if (!text) return text;
    const lines = text.split('\n');
    // The first six lines are product-authored guidance; project names and facts follow them.
    lines[2] = 'Project memory is managed by the Host. Use update_state for supported changes:';
    lines[4] = '  - Join or leave: update_state target "project", action "join" or "leave", project=<slug>. Only joined projects are included below.';
    if (recall.alsoMemberOf.length) lines[lines.length - 1] = `Also a member of: ${recall.alsoMemberOf.map(item => `${item.name} (${item.slug})`).join(', ')}; their additional facts are not included in this prompt.`;
    return omitDiskLookup(lines.join('\n'));
  });
  wrap('resolveFrozenMemoryPrompt', (resolve, args) => {
    const nativeSnapshot = /^(?:Your memory lives in a folder at |User memory lives under |Projects live under )/m.test(args.snapshot?.render ?? '');
    // Refresh an old rendering once from the same stores; never change or delete the facts.
    return resolve(nativeSnapshot ? { ...args, snapshot: null } : args);
  });
  wrap('renderAutomationsSystemPrompt', (render, ...args) => {
    const text = render(...args); if (!text) return text;
    const lines = text.split('\n');
    lines[1] = 'Routines are saved on the Host. Use update_state target "routine" for changes. Their Host folders are identifiers, not paths readable through a remote MCP machine. For external work, save the provider and intended machine with the task intent; discover its current tools on each run.';
    return lines.join('\n');
  });
  wrap('renderChannelsSystemPrompt', (render, ...args) => {
    const text = render(...args); if (!text) return text;
    const lines = text.split('\n');
    lines[1] = 'Channel configuration and credentials are stored by the Host, separately from external machines. Use update_state target "channel", action "disconnect" with the platform for supported disconnections.';
    return lines.join('\n');
  });
  wrap('renderAgentDirectorySystemPrompt', (render, others, groups, _root, options) => {
    const text = render(others, groups, undefined, options);
    return text.replace('listed below, and you can read their files for fuller detail', 'listed below; their Host files are not available on remote machines');
  });
  return adapted;
}

function externalProfileSnapshot(snapshot) {
  if (!snapshot?.profileSection) return snapshot;
  // Older persisted profile snapshots can contain these native instructions until compaction.
  const profileSection = snapshot.profileSection.split('\n').filter(line =>
    !line.startsWith('Your profile is a JSON config file at ') &&
    !line.startsWith('Your profile picture is NOT part of that config ') &&
    !line.startsWith('Your per-agent settings live in a separate JSON config file at ')).join('\n');
  return { ...snapshot, profileSection };
}

/** Decorate exports before downstream recovered factories capture them. No generated file edits. */
export function executionPromptBindings(_module, original, disabled = boxDisabled()) {
  if (!disabled) return original;
  const adapted = { ...original };
  if (original.createPromptCollectorGlue) adapted.createPromptCollectorGlue = host => {
    const glue = original.createPromptCollectorGlue(host);
    return { ...glue, getRemoteBoxSection: externalExecutionSection, getComputerSection: () => null };
  };
  if (original.createSystemPromptAssembly) adapted.createSystemPromptAssembly = deps => {
    const assembly = original.createSystemPromptAssembly({ ...deps,
      agentProfileProvider: () => {
        const provider = deps.agentProfileProvider();
        return provider == null ? provider : () => {
          const profile = provider();
          return profile == null ? profile : { ...profile, filePath: '', settingsFilePath: '' };
        };
      },
      skillStore: () => null,
      agentsRootDir: () => undefined,
      isUserFormEnabled: () => false,
      remoteBoxSection: externalExecutionSection,
      computerSection: () => null,
    });
    return { ...assembly,
      getSystemPrompt: (snapshot, ...args) => assembly.getSystemPrompt(externalProfileSnapshot(snapshot), ...args),
      createSystemPromptGeneratorForRun: (snapshot, ...args) => assembly.createSystemPromptGeneratorForRun(externalProfileSnapshot(snapshot), ...args),
    };
  };
  return adapted;
}

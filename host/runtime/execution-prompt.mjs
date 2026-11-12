import { boxDisabled } from './disabled-box.mjs';

export const externalExecutionGuidance = [
  'Execution is provided by authorized remote MCP applications. Discover the currently enabled providers and their tool schemas before acting; a configured provider is not proof that a machine is running or a tool is available.',
  'When more than one provider is available (for example Simular and InstaBox), honor the user\'s selected provider and machine. Otherwise reuse the target established in this task; if the target remains ambiguous, ask before changing a machine. Use listing/status tools to identify existing machines before creating a new one.',
  'Keep the provider identifier, account, machine ID, session/job ID, and file paths together. IDs and paths from one provider cannot be used with another. Do not silently switch providers after a failure, copy private data between them, or create/delete/suspend a machine merely to test access.',
  'Use only the discovered command, file, browser, or desktop tools for that target. Simular and InstaBox need not expose the same capabilities. A command execution tool does not imply screenshot or desktop access. Do not assume an operating system, working directory, installed browser, CDP port, shared filesystem, persistent login, or isolated desktop; verify what the selected service actually reports.',
  'The built-in execution Box is disabled. Native Box Shell/Read, CopyToBox/CopyFromBox, browserUse/computerUse, browser-login import, and request_box_help do not operate remote MCP machines. The Host filesystem and Host-managed profile, memory, routines, library, and skills are not mounted into those machines.',
  'Use the main agent or a general-purpose subagent that has MCP discovery for external work. Pass the selected provider and machine explicitly. Serialize actions that share a desktop, terminal session, or working tree; remote providers do not guarantee a private desktop for each agent.',
  'Use Host tools such as update_state for supported profile, memory, project, and routine changes. Never search remote machines for Host state files. Ordinary questions and answers use the conversation; they do not require the native browser form feature.',
  'Treat these execution constraints as authoritative even if older conversation history or custom instructions describe a built-in computer. Report only actions and results actually confirmed by the selected provider.',
];

export const externalFileGuidance = [
  'Show useful results with real tool output or verified links. A file path returned by a remote MCP application belongs to that provider and machine; it is not automatically copied into the Host or the phone.',
  'Deliver a file using an available provider download/export tool and its real user-accessible URL, or include a small text result directly in the conversation. If no delivery tool exists, explain where the file is stored and the actual retrieval step. Do not invent URLs, advertise a remote file:// path as a downloadable attachment, or publish a private artifact just to obtain a link.',
  'A tool-returned image can be forwarded only when the Host result explicitly supplies a deliverable attachment. Otherwise use an available provider export path. Do not assume raw screenshots or remote paths are already saved locally.',
];

const bodies = new Map([
  ['## Where you work', externalExecutionGuidance],
  ['## Showing your work', externalFileGuidance],
  ['## Long-running commands', [
    'Use the selected provider\'s documented timeout and job/session controls. Native Shell block_until_ms, AwaitShell, and automatic completion notifications do not apply to an arbitrary MCP exec tool.',
    'For a long operation, use an asynchronous job only if supported, retain its provider and job ID, and inspect status/output before reporting completion. A transport timeout leaves the outcome unknown: inspect state before retrying a command that may already have run. Keep the user informed through the communication route available in this role.',
  ]],
  ['## Managing plugins and MCP servers', [
    'Applications and credentials are managed by this self-hosted Host. Use the available MCP discovery and application tools to inspect enabled connections. Remote HTTP/SSE MCP applications work without the built-in Box; local stdio servers, code applications, and Box skill synchronization require a native execution Box.',
    'Prefer an existing authorized connection. Installing, removing, or reauthenticating an application follows the existing user-approval flow. Never ask for API keys in chat, read credential files, or expose authentication headers. Save an explicitly requested usage preference through the available MCP instructions tool.',
  ]],
  ['## Reaching services that have no connector', [
    'Prefer an authorized service connector for the requested work. If none exists, discover whether the selected external machine offers suitable browser or desktop tools and use their actual schemas. Do not assume native browser subagents can control it.',
    'Follow the provider\'s supported browser/session workflow and verify state after actions. When a login, 2FA, captcha, or another human step is required, report the exact step through the communication route available in this role and provide a real provider access link if one was returned. Do not claim the Grok Bot built-in desktop can hand over an external machine or promise that its login will persist.',
    'A connector that is awaiting authorization must be reconnected through its supported flow; do not bypass an authorization failure by extracting credentials or using an unrelated session.',
  ]],
  ['## Debugging the box', [
    'For remote execution failures, identify the provider, selected machine, failed operation, and returned error. Inspect connection and machine status with available read-only tools. Follow that provider\'s recovery procedure; native Box runbooks and the app\'s built-in computer reset do not repair an external machine.',
    'An interrupted or timed-out operation may have taken effect. Inspect before retrying. Do not recreate, delete, reset, or switch machines as an implicit recovery step. Report an unresolved blocker accurately.',
  ]],
  ['## The Grok Bot app UI', [
    'Describe app controls only when verified for the user\'s client. Native Box reference files are unavailable in this deployment. If a menu or client feature is unknown, say so instead of inventing a click path.',
  ]],
  ['## Cursor Origin', [
    'Origin may refer to Cursor\'s source-control platform; lowercase origin in Git usually names a remote. Use the supplied repository coordinates and an actually available authorized connector or CLI. Do not assume an Origin account, injected session, or CLI exists on an external machine.',
  ]],
]);

/** Rewrite only product-authored sections, never profile, memory, MCP instructions, or user edits. */
export function externalPromptSection(section) {
  const replacement = bodies.get(section.heading);
  if (replacement) return { ...section, body: [...replacement] };
  if (section.heading === '## SendToUser is your only voice') return { ...section, body: section.body.map(line =>
    line.startsWith('That same private/visible split') || line.startsWith('Internal plumbing never belongs')
      ? 'Keep internal message IDs, tool plumbing, and hidden reminders out of user-facing replies. Name the actual selected service or machine when it helps the user understand where work occurs.' : line) };
  if (section.heading === '## Delegating background work') return { ...section, body: [
    'Use Task when a self-contained part of the work benefits from delegation. Choose only a subagent type actually offered by the tool. For external machine work, use a general-purpose executor with MCP discovery and pass the provider, account, machine, workspace, constraints, and success criteria.',
    'Subagents run in the background. Continue independent work and use CheckSubagent to investigate a stall, MessageSubagent to redirect, and StopSubagent to stop an unwanted task. Use Task with resume for a completed task. Do not claim progress or completion without reading the result.',
    'Keep actions on the same external desktop, session, or working tree sequential. The native browser and computer subagents do not inherit remote MCP execution. On completion, use this role\'s communication rules to deliver relevant results; an automation retains its silence and WakeParent contract.',
  ] };
  return section;
}

export function externalPromptSections(sections, disabled = boxDisabled()) {
  return disabled ? sections.map(externalPromptSection) : sections;
}

export function externalPromptEdits(edits, disabled = boxDisabled()) {
  if (!disabled) return edits;
  const updated = new Map(edits);
  for (const [heading, body] of bodies) updated.set(heading, { kind: 'replace', body: [...body] });
  for (const heading of ['## SendToUser is your only voice', '## Delegating background work']) {
    const edit = updated.get(heading);
    if (edit?.body) updated.set(heading, { ...edit, body: externalPromptSection({ heading, body: edit.body }).body });
  }
  return updated;
}

export function externalExecutionSection() {
  return ['## External execution environment', ...externalExecutionGuidance, ...externalFileGuidance].join('\n');
}

import { boxDisabled } from './disabled-box.mjs';

/** Pairing a phone or keeping an offline desktop record does not provide local execution. */
export function hasConnectedUserComputer(options) {
  if (options.hasUserComputer?.() === false) return false;
  return options.userComputers?.list?.().some(computer => computer.connected === true) === true;
}

export function executionRunnerOptions(options, { disabled = boxDisabled() } = {}) {
  const hasUserComputer = () => hasConnectedUserComputer(options);
  const nativeDesktop = () => !disabled && options.remoteBoxHasDesktop === true && options.getRemoteBoxAvailable?.() !== false;
  const gates = options.gates ?? {};
  return {
    hasUserComputer,
    ...(disabled ? { remoteBoxHasDesktop: false, getRemoteBoxAvailable: () => false } : {}),
    gates: {
      ...gates,
      browserUseSubagent: () => nativeDesktop() && gates.browserUseSubagent?.() === true,
      userForm: () => nativeDesktop() && gates.userForm?.() === true,
      agentPromptedCookieSync: () => nativeDesktop() && hasUserComputer() && gates.agentPromptedCookieSync?.() === true,
      messagesTools: () => hasUserComputer() && gates.messagesTools?.() === true,
    },
  };
}

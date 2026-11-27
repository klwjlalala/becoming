import { DesktopError } from './model-vault.mjs';

function id(value) {
  if ((typeof value !== 'string' && typeof value !== 'number') ||
      !/^[A-Za-z0-9_-]{1,128}$/.test(String(value)))
    throw new DesktopError('invalid_identifier');
  return encodeURIComponent(String(value));
}
function query(input, allowed) {
  const params = new URLSearchParams();
  for (const key of allowed) {
    const value = input?.[key];
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  return params.size ? '?' + params.toString() : '';
}
function object(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new DesktopError('invalid_request');
  return value;
}
export function operations(service, models, confirmClear) {
  const r = (method, path, data) => service.request(method, path, data);
  const conversation = value => '/conversations/' + id(value);
  return Object.freeze({
    health: () => r('GET', '/health'),
    capabilities: () => r('GET', '/capabilities'),
    modelStatus: () => models.status(),
    modelTest: input => models.test(object(input)),
    modelConfigure: input => models.configure(object(input)),
    modelForgetSaved: () => models.forgetSaved(),
    conversations: input => r('GET', '/conversations' + query(input, ['limit','offset','include_archived'])),
    conversationCreate: input => r('POST', '/conversations', object(input)),
    conversationGet: value => r('GET', conversation(value)),
    conversationUpdate: (value, input) => r('PATCH', conversation(value), object(input)),
    conversationDelete: value => r('DELETE', conversation(value)),
    messages: (value, input) => r('GET', conversation(value) + '/messages' + query(input, ['limit','before_id'])),
    send: (value, content) => r('POST', conversation(value) + '/messages', { content }),
    confirmGrowth: (value, token) => r('POST', conversation(value) + '/confirm', { token }),
    cancelGrowth: value => r('POST', conversation(value) + '/cancel'),
    goals: input => r('GET', '/growth/goals' + query(input, ['offset'])),
    goal: (value, input) => r('GET', '/growth/goals/' + id(value) + query(input, ['offset'])),
    previewGrowth: input => r('POST', '/growth/changes', object(input)),
    applyGrowth: token => r('POST', '/growth/changes/' + id(token) + '/confirm'),
    cancelPreview: token => r('POST', '/growth/changes/' + id(token) + '/cancel'),
    memories: () => r('GET', '/memories'),
    forgetMemory: key => r('DELETE', '/memories/' + id(key)),
    allowMemory: key => r('POST', '/memories/' + id(key) + '/allow'),
    claims: input => r('GET', '/understanding/claims' + query(input, ['limit','offset'])),
    claim: value => r('GET', '/understanding/claims/' + id(value)),
    backgroundStatus: () => r('GET', '/background/status'),
    backgroundJobs: input => r('GET', '/background/jobs' + query(input, ['limit','status','source_turn_id'])),
    exportData: () => r('GET', '/data/export'),
    clearData: async () => {
      // Destructive clearing is confirmed using the native dialog, not a
      // renderer-supplied boolean or a freely accessible confirmation token.
      if (!await confirmClear()) return { success: false, cancelled: true };
      const preview = await r('POST', '/data/clear');
      return r('POST', '/data/clear/confirm', { token: preview.token });
    },
  });
}

export function registerIPC(ipcMain, handlers, allowedSender) {
  for (const [name, handler] of Object.entries(handlers)) {
    ipcMain.handle('becoming:' + name, async (event, ...args) => {
      if (!allowedSender(event)) return { ok: false, error: { code: 'ipc_forbidden' } };
      try { return { ok: true, result: await handler(...args) }; }
      catch (error) {
        const code = typeof error.code === 'string' && /^[a-z][a-z0-9_]{0,79}$/.test(error.code)
          ? error.code : 'desktop_request_failed';
        return { ok: false, error: { code,
          status: Number.isInteger(error.status) ? error.status : null,
          requestId: typeof error.requestId === 'string' && /^[A-Za-z0-9._-]{1,64}$/.test(error.requestId)
            ? error.requestId : null } };
      }
    });
  }
  return () => { for (const name of Object.keys(handlers)) ipcMain.removeHandler('becoming:' + name); };
}

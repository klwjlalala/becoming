import { app, ipcMain, safeStorage } from 'electron';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BecomingService } from '../main/becoming-service.mjs';
import { ModelVault, ModelController } from '../main/model-vault.mjs';
import { operations, registerIPC } from '../main/ipc.mjs';
import { createWindow, loadWindow, trustedSender } from '../main/window.mjs';
const timer = setTimeout(() => { console.error('Electron smoke timeout'); app.exit(1); }, 90000);
let directory, service, win, dispose, exit = 0;
async function main() {
try {
  console.log('smoke: waiting for app ready');
  await app.whenReady();
  console.log('smoke: app ready');
  directory = await mkdtemp(join(tmpdir(), 'becoming-electron-'));
  service = new BecomingService({ dataDir: directory });
  const models = new ModelController(service, new ModelVault({ file: join(directory, 'model.enc'), safeStorage }));
  await models.start({ demo: true });
  console.log('smoke: Python service ready');
  win = createWindow({ show: false });
  dispose = registerIPC(ipcMain, operations(service, models, async () => false), event => trustedSender(win, event));
  win.webContents.on('preload-error', (_event, _path, error) => console.error('smoke: preload error', error.message));
  win.webContents.on('render-process-gone', (_event, details) => console.error('smoke: renderer gone', details.reason));
  await loadWindow(win);
  console.log('smoke: window loaded');
  const result = await win.webContents.executeJavaScript(`(async () => {
    const bridge = window.becoming;
    const health = await bridge.health();
    const model = await bridge.modelStatus();
    const conversation = await bridge.conversationCreate({title: 'Electron smoke'});
    const message = await bridge.send(conversation.result.id, 'synthetic test message');
    const history = await bridge.messages(conversation.result.id);
    const clear = await bridge.clearData();
    return {health, model, message, history, clear, node: typeof require,
      generic: typeof bridge.request, token: typeof bridge.token};
  })()`);
  console.log('smoke: IPC returned');
  assert.equal(result.health.ok, true);
  assert.equal(result.model.ok, true);
  assert.equal(result.model.result.demo, true);
  assert.equal(result.message.ok, true);
  assert.equal(result.history.result.items.length, 1);
  assert.equal(result.clear.result.cancelled, true);
  assert.equal(result.node, 'undefined');
  assert.equal(result.generic, 'undefined');
  assert.equal(result.token, 'undefined');
  console.log('Electron renderer → preload → IPC → Python smoke passed');
} catch (error) { console.error(error); exit = 1; }
finally {
  dispose?.();
  if (win && !win.isDestroyed()) win.destroy();
  console.log('smoke: stopping service');
  await service?.stop().catch(() => { exit = 1; });
  if (directory) await rm(directory, { recursive: true, force: true }).catch(() => { exit = 1; });
  clearTimeout(timer);
  app.exit(exit);
}

}
// Do not await app readiness at ESM module scope: Electron must finish loading
// the entry module before it can signal readiness.
void main();

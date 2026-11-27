import { app, dialog, ipcMain, safeStorage } from 'electron';
import { join } from 'node:path';
import { BecomingService } from './becoming-service.mjs';
import { ModelVault, ModelController } from './model-vault.mjs';
import { operations, registerIPC } from './ipc.mjs';
import { createWindow, loadWindow, trustedSender } from './window.mjs';

let win, service, unregister;
let quitting = false;
let stopped = false;
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win && !win.isDestroyed()) { if (win.isMinimized()) win.restore(); win.focus(); }
  });
  app.on('before-quit', event => {
    if (stopped || !service) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    unregister?.();
    service.stop().catch(() => {}).finally(() => { stopped = true; app.quit(); });
  });
  app.on('window-all-closed', () => app.quit());
  app.whenReady().then(async () => {
    const directory = app.getPath('userData');
    service = new BecomingService({
      dataDir: join(directory, 'data'),
      python: process.env.BECOMING_PYTHON || 'python',
    });
    const models = new ModelController(service, new ModelVault({
      file: join(directory, 'model-config.enc'), safeStorage,
    }));
    await models.start();
    win = createWindow();
    unregister = registerIPC(ipcMain, operations(service, models, async () => {
      const answer = await dialog.showMessageBox(win, {
        type: 'warning', buttons: ['取消', '清除全部本地数据'], defaultId: 0, cancelId: 0,
        message: '确定清除全部本地对话、记忆及成长数据？',
        detail: '此操作不可撤销，不会删除第三方模型服务或备份中的副本。',
      });
      return answer.response === 1;
    }), event => trustedSender(win, event));
    await loadWindow(win);
  }).catch(() => {
    dialog.showErrorBox('Becoming 无法启动', '请检查 Python 3.11+ 环境和项目依赖。');
    app.quit();
  });
}

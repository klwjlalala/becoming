import { BrowserWindow } from 'electron';
import { fileURLToPath, pathToFileURL } from 'node:url';
const page = fileURLToPath(new URL('../renderer/index.html', import.meta.url));
export const pageURL = pathToFileURL(page).href;

export function createWindow({ show = true } = {}) {
  const win = new BrowserWindow({
    width: 1100, height: 760, minWidth: 640, minHeight: 480,
    show, backgroundColor: '#16191d',
    webPreferences: {
      preload: fileURLToPath(new URL('../preload.cjs', import.meta.url)),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      webSecurity: true, webviewTag: false,
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', event => event.preventDefault());
  win.webContents.on('will-attach-webview', event => event.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  win.webContents.session.setPermissionCheckHandler(() => false);
  return win;
}

export function trustedSender(win, event) {
  return Boolean(win && !win.isDestroyed() && event.sender === win.webContents &&
    event.senderFrame === win.webContents.mainFrame &&
    event.senderFrame?.url === pageURL);
}

export async function loadWindow(win) { await win.loadFile(page); }

import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';

export class DesktopError extends Error {
  constructor(code) { super(code); this.code = code; }
}

export function modelConfig(input) {
  if (!input || typeof input !== 'object') throw new DesktopError('invalid_model_config');
  const { base_url, api_key, model } = input;
  if (![base_url, api_key, model].every(x => typeof x === 'string' && x.trim()) ||
      base_url.length > 500 || api_key.length > 2000 || model.length > 200)
    throw new DesktopError('invalid_model_config');
  let url;
  try { url = new URL(base_url.trim()); }
  catch { throw new DesktopError('invalid_model_config'); }
  // Allow local development endpoints, but never send credentials to remote HTTP.
  if (url.username || url.password || url.search || url.hash ||
      !(url.protocol === 'https:' ||
        (url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))))
    throw new DesktopError('invalid_model_url');
  return { base_url: url.href.replace(/\/$/, ''), api_key: api_key.trim(), model: model.trim() };
}

export class ModelVault {
  constructor({ file, safeStorage, platform = process.platform }) {
    this.file = file;
    this.safeStorage = safeStorage;
    this.platform = platform;
  }
  available() {
    try {
      return this.safeStorage.isEncryptionAvailable() &&
        (this.platform !== 'linux' ||
         ['gnome_libsecret', 'kwallet', 'kwallet5', 'kwallet6'].includes(
           this.safeStorage.getSelectedStorageBackend()));
    } catch { return false; }
  }
  async load() {
    let encrypted;
    try { encrypted = await readFile(this.file); }
    catch (error) {
      if (error.code === 'ENOENT') return null;
      throw new DesktopError('vault_read_failed');
    }
    if (!this.available()) throw new DesktopError('secure_storage_unavailable');
    try {
      return modelConfig(JSON.parse(this.safeStorage.decryptString(encrypted)));
    } catch { throw new DesktopError('vault_read_failed'); }
  }
  async save(config) {
    if (!this.available()) throw new DesktopError('secure_storage_unavailable');
    const validated = modelConfig(config);
    const temporary = this.file + '.' + randomUUID() + '.tmp';
    try {
      await mkdir(dirname(this.file), { recursive: true, mode: 0o700 });
      const encrypted = this.safeStorage.encryptString(JSON.stringify(validated));
      await writeFile(temporary, encrypted, { mode: 0o600, flag: 'wx' });
      await rename(temporary, this.file);
    } catch { throw new DesktopError('vault_write_failed'); }
    finally { await rm(temporary, { force: true }).catch(() => {}); }
  }
  async clear() {
    try { await rm(this.file, { force: true }); }
    catch { throw new DesktopError('vault_delete_failed'); }
  }
}

export class ModelController {
  #saved = null;
  #session = null;
  #error = null;
  #tail = Promise.resolve();
  constructor(service, vault) { this.service = service; this.vault = vault; }
  async start({ demo = false } = {}) {
    try { this.#saved = await this.vault.load(); }
    catch (error) { this.#error = error.code || 'vault_read_failed'; }
    this.#session = demo ? null : this.#saved;
    await this.service.start({ demo, modelConfig: this.#session });
  }
  async status() {
    const current = await this.service.request('GET', '/model/config');
    return {
      configured: current.configured, demo: current.demo,
      base_url: current.base_url, model: current.model,
      key_configured: current.api_key_configured,
      secure_storage_available: this.vault.available(),
      saved: Boolean(this.#saved), storage_error: this.#error,
    };
  }
  #resolve(input) {
    if (!input || typeof input !== 'object') throw new DesktopError('invalid_model_config');
    const { base_url, model, api_key } = input;
    // Reuse a key only for precisely the same configured endpoint.
    const previous = this.#session || this.#saved;
    const candidate = modelConfig({ base_url, model,
      api_key: api_key || (previous && previous.api_key) || '' });
    if (!api_key && candidate.base_url !== previous?.base_url)
      throw new DesktopError('model_key_required');
    return candidate;
  }
  async test(input) {
    const config = this.#resolve(input);
    await this.service.request('POST', '/model/test', config);
    return { success: true, model: config.model };
  }
  configure(input) {
    const operation = this.#tail.then(async () => {
      const config = this.#resolve(input);
      const persist = input.persist === true;
      if (persist && !this.vault.available()) throw new DesktopError('secure_storage_unavailable');
      await this.service.request('POST', '/model/test', config);
      await this.service.request('PUT', '/model/config', config);
      this.#session = config;
      this.#error = null;
      // If OS storage fails after a successful runtime update, explicitly
      // report that the new config is session-only; never claim it was saved.
      if (persist) {
        try { await this.vault.save(config); this.#saved = config; }
        catch (error) { this.#error = error.code || 'vault_write_failed'; }
      }
      return { ...await this.status(), applied: true,
        persisted: persist && !this.#error };
    });
    this.#tail = operation.catch(() => {});
    return operation;
  }
  forgetSaved() {
    const operation = this.#tail.then(async () => {
      await this.vault.clear();
      this.#saved = null;
      this.#error = null;
      return { saved: false, session_retained: Boolean(this.#session) };
    });
    this.#tail = operation.catch(() => {});
    return operation;
  }
}

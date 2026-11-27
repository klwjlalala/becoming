/** Headless Node.js service manager, intended for Electron Main only. */
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const projectRoot = fileURLToPath(new URL('../../', import.meta.url));

export class ServiceError extends Error {
  constructor(code, status = null, requestId = null) {
    super(code);
    this.name = 'ServiceError';
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

export class BecomingService {
  #child = null;
  #closed = null;
  #origin = null;
  #token = null;
  #starting = null;
  #stopping = null;

  constructor({ dataDir, python = 'python', rootDir = projectRoot,
    startupTimeoutMs = 20000, requestTimeoutMs = 120000 } = {}) {
    if (typeof dataDir !== 'string' || !dataDir.trim()) {
      throw new TypeError('dataDir is required');
    }
    this.dataDir = resolve(dataDir);
    this.python = python;
    this.rootDir = resolve(rootDir);
    this.startupTimeoutMs = startupTimeoutMs;
    this.requestTimeoutMs = requestTimeoutMs;
  }

  // Main-process diagnostics only. Never expose this through preload/IPC.
  get origin() { return this.#origin; }
  get running() { return this.#origin !== null && this.#child !== null; }

  async start(options = {}) {
    if (this.#stopping) await this.#stopping;
    if (this.running) return;
    if (!this.#starting) {
      this.#starting = this.#launch(options).finally(() => { this.#starting = null; });
    }
    return this.#starting;
  }

  async #launch({ demo = false, modelConfig = null,
    longMemory = true, personalUnderstanding = true } = {}) {
    if (demo && modelConfig) throw new TypeError('Choose demo or a real model');
    if (modelConfig && !['base_url', 'api_key', 'model'].every(
      key => typeof modelConfig[key] === 'string' && modelConfig[key].trim())) {
      throw new TypeError('Incomplete model configuration');
    }
    await mkdir(this.dataDir, { recursive: true });
    // Do not inherit a previous developer session's model or database settings.
    const env = Object.fromEntries(Object.entries(process.env)
      .filter(([key]) => !key.toUpperCase().startsWith('BECOMING_')));
    const token = randomBytes(32).toString('hex');
    Object.assign(env, {
      PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8',
      BECOMING_SERVICE_TOKEN: token,
      BECOMING_API_DB: join(this.dataDir, 'conversations.sqlite3'),
      BECOMING_API_GROWTH_DB: join(this.dataDir, 'growth.sqlite3'),
      BECOMING_DEMO: demo ? '1' : '0',
      BECOMING_ENABLE_LONG_MEMORY: longMemory ? '1' : '0',
      BECOMING_ENABLE_PERSONAL_UNDERSTANDING: personalUnderstanding ? '1' : '0',
    });
    if (modelConfig) Object.assign(env, {
      BECOMING_BASE_URL: modelConfig.base_url,
      BECOMING_API_KEY: modelConfig.api_key,
      BECOMING_MODEL: modelConfig.model,
    });
    const child = spawn(this.python, ['-m', 'becoming.desktop_service'], {
      cwd: this.rootDir, env, shell: false, windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    this.#child = child;
    this.#token = token;
    let ended = false;
    let spawnFailed = false;
    let port = null;
    child.on('error', () => { spawnFailed = true; });
    child.stdin.on('error', () => {});
    // Drain logs but do not forward private model or user data to the renderer.
    child.stderr.resume();
    const lines = createInterface({ input: child.stdout });
    lines.on('line', line => {
      if (port !== null || !line.startsWith('BECOMING_BOUND ')) return;
      try {
        const info = JSON.parse(line.slice('BECOMING_BOUND '.length));
        if (info.api_version === '1' && Number.isInteger(info.port)
            && info.port > 0 && info.port <= 65535) port = info.port;
      } catch { /* ignore malformed startup lines */ }
    });
    const closed = new Promise(done => child.once('close', () => {
      ended = true;
      if (this.#child === child) {
        this.#child = null;
        this.#origin = null;
        this.#token = null;
      }
      done();
    }));
    this.#closed = closed;
    const deadline = Date.now() + this.startupTimeoutMs;
    try {
      while (Date.now() < deadline) {
        if (spawnFailed || ended) throw new ServiceError('service_start_failed');
        if (port !== null) {
          const origin = 'http://127.0.0.1:' + port;
          try {
            const response = await fetch(origin + '/api/v1/health', {
              headers: { Authorization: 'Bearer ' + token },
              signal: AbortSignal.timeout(750), redirect: 'error',
            });
            const body = await response.json();
            if (response.ok && body.status === 'ok' && body.api_version === '1' && !ended) {
              this.#origin = origin;
              return;
            }
          } catch { /* readiness probe retries until deadline */ }
        }
        await delay(75);
      }
      throw new ServiceError('service_start_timeout');
    } catch (error) {
      await this.#shutdown(child, closed);
      throw error;
    }
  }

  async #shutdown(child, closed) {
    if (!child) return;
    const wait = async ms => {
      const controller = new AbortController();
      try {
        return await Promise.race([
          closed.then(() => true),
          delay(ms, false, { signal: controller.signal }),
        ]);
      } finally { controller.abort(); }
    };
    if (!child.stdin.destroyed) child.stdin.end();
    if (await wait(15000)) return;
    child.kill('SIGTERM');
    if (await wait(3000)) return;
    child.kill('SIGKILL');
    if (!await wait(3000)) throw new ServiceError('service_stop_failed');
  }

  async stop() {
    if (!this.#stopping) {
      this.#stopping = (async () => {
        if (this.#starting) await this.#starting.catch(() => {});
        await this.#shutdown(this.#child, this.#closed);
      })().finally(() => { this.#stopping = null; });
    }
    return this.#stopping;
  }

  async request(method, path, body) {
    if (!this.running) throw new ServiceError('service_not_running');
    if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)
        || typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) {
      throw new TypeError('Invalid API request');
    }
    const url = new URL('/api/v1' + path, this.#origin);
    if (url.origin !== this.#origin || !url.pathname.startsWith('/api/v1/')) {
      throw new TypeError('Invalid API path');
    }
    let response;
    try {
      response = await fetch(url, {
        method, headers: {
          Authorization: 'Bearer ' + this.#token,
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(this.requestTimeoutMs), redirect: 'error',
      });
    } catch {
      throw new ServiceError('service_connection_failed');
    }
    let payload;
    try { payload = await response.json(); }
    catch { throw new ServiceError('invalid_service_response', response.status); }
    if (!response.ok) {
      throw new ServiceError(payload?.error?.code || 'service_request_failed',
        response.status, payload?.error?.request_id || null);
    }
    return payload;
  }
}

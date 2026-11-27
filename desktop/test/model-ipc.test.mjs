import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ModelVault, ModelController } from '../main/model-vault.mjs';
import { operations, registerIPC } from '../main/ipc.mjs';
const config = { base_url: 'https://example.test/v1', api_key: 'synthetic-key', model: 'test-model' };
const fakeStorage = { isEncryptionAvailable: () => true, getSelectedStorageBackend: () => 'gnome_libsecret',
  encryptString: text => Buffer.from(text).map(n => n ^ 77),
  decryptString: bytes => Buffer.from(bytes).map(n => n ^ 77).toString() };
test('vault round trip, encrypted file and no Linux plaintext fallback', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'becoming-vault-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const file = join(directory, 'config.enc');
  const vault = new ModelVault({ file, safeStorage: fakeStorage, platform: 'linux' });
  assert.equal(await vault.load(), null);
  await vault.save(config);
  assert.equal((await readFile(file)).includes(Buffer.from(config.api_key)), false);
  assert.deepEqual(await vault.load(), config);
  const insecure = new ModelVault({ file, platform: 'linux',
    safeStorage: { ...fakeStorage, getSelectedStorageBackend: () => 'basic_text' } });
  assert.equal(insecure.available(), false);
  await assert.rejects(insecure.save(config), { code: 'secure_storage_unavailable' });
  await assert.rejects(insecure.load(), { code: 'secure_storage_unavailable' });
  await vault.clear();
  assert.equal(await vault.load(), null);
});
test('model test before update, no key return, no reuse on a different URL', async () => {
  const calls = [];
  let current = { configured: false };
  const service = { start: async () => {}, request: async (method, path, body) => {
    calls.push([method, path]);
    if (method === 'PUT') current = { configured: true, model: body.model, base_url: body.base_url, api_key_configured: true };
    return current;
  }};
  const vault = { load: async () => null, available: () => false };
  const controller = new ModelController(service, vault);
  await controller.start();
  await assert.rejects(controller.configure({ ...config, persist: true }), { code: 'secure_storage_unavailable' });
  assert.equal(calls.length, 0);
  const result = await controller.configure(config);
  assert.equal(result.applied, true);
  assert.equal(result.persisted, false);
  assert.equal(JSON.stringify(result).includes(config.api_key), false);
  assert.deepEqual(calls.slice(0,2), [['POST','/model/test'],['PUT','/model/config']]);
  await assert.rejects(controller.test({ base_url: 'https://other.test/v1', model: 'test-model' }), { code: 'model_key_required' });
});
test('explicit IPC mapping, forbidden sender, native clear cancellation, sanitized failure', async () => {
  const calls = [];
  const service = { request: async (...args) => { calls.push(args); return { success: true }; } };
  const handlers = operations(service, {}, async () => false);
  const channels = new Map();
  const ipc = { handle: (name, fn) => channels.set(name, fn), removeHandler: name => channels.delete(name) };
  const dispose = registerIPC(ipc, handlers, event => event.trusted === true);
  assert.equal(channels.has('becoming:request'), false);
  assert.equal((await channels.get('becoming:health')({ trusted: false })).error.code, 'ipc_forbidden');
  assert.equal(calls.length, 0);
  assert.equal((await channels.get('becoming:conversationGet')({ trusted: true }, '../private')).error.code, 'invalid_identifier');
  assert.equal((await channels.get('becoming:clearData')({ trusted: true })).result.cancelled, true);
  assert.equal(calls.length, 0);
  assert.equal((await channels.get('becoming:send')({ trusted: true }, 'abc', 'hello')).ok, true);
  assert.deepEqual(calls[0], ['POST','/conversations/abc/messages',{ content: 'hello' }]);
  dispose(); assert.equal(channels.size, 0);
});

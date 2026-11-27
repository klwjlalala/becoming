import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BecomingService } from '../main/becoming-service.mjs';

async function fixture(t, options = {}) {
  const dataDir = await mkdtemp(join(tmpdir(), 'becoming-desktop-'));
  const service = new BecomingService({ dataDir, ...options });
  t.after(async () => {
    await service.stop();
    await rm(dataDir, { recursive: true, force: true });
  });
  return service;
}
const demo = { demo: true, longMemory: false, personalUnderstanding: false };

test('real Python child: private loopback, JSON errors, persistence and restart', async t => {
  const service = await fixture(t);
  await Promise.all([service.start(demo), service.start(demo)]);
  assert.match(service.origin, /^http:\/\/127\.0\.0\.1:\d+$/);
  const health = await service.request('GET', '/health');
  assert.equal(health.api_version, '1');
  assert.equal(health.model_configured, true);
  for (const path of ['/api/v1/health', '/api/v1/data/export', '/docs']) {
    const response = await fetch(service.origin + path);
    assert.equal(response.status, 401);
    assert.equal((await response.json()).error.code, 'service_unauthorized');
  }
  const wrong = await fetch(service.origin + '/api/v1/health', {
    headers: { Authorization: 'Bearer wrong' },
  });
  assert.equal(wrong.status, 401);
  await assert.rejects(service.request('GET', '//example.com'), TypeError);
  await assert.rejects(service.request('GET', '/../health'), TypeError);
  await assert.rejects(service.request('GET', '/conversations/not-real'),
    error => error.code === 'conversation_not_found' && error.status === 404 && !!error.requestId);
  const conversation = await service.request('POST', '/conversations', { title: '桌面端联调' });
  const path = '/conversations/' + conversation.id + '/messages';
  const message = await service.request('POST', path, { content: '这是虚构测试数据。' });
  assert.ok(message.reply);
  assert.ok(message.message_id);
  assert.equal((await service.request('GET', path)).items.length, 1);
  const preview = await service.request('POST', '/growth/changes', {
    tool: 'create_goal', args: { text: '测试目标' },
  });
  assert.ok(preview.confirmation_required);
  assert.equal((await service.request('POST', '/growth/changes/' + preview.token + '/confirm')).success, true);
  await Promise.all([service.stop(), service.stop()]);
  assert.equal(service.running, false);
  await assert.rejects(service.request('GET', '/health'), { code: 'service_not_running' });
  await service.start(demo);
  assert.equal((await service.request('GET', path)).items[0].user, '这是虚构测试数据。');
  assert.equal((await service.request('GET', '/growth/goals')).items[0].text, '测试目标');
});

test('start without model ignores ambient configuration and allows setup', async t => {
  const service = await fixture(t);
  await service.start();
  assert.equal((await service.request('GET', '/health')).model_configured, false);
  const conversation = await service.request('POST', '/conversations', { title: '未配置模型' });
  await assert.rejects(service.request('POST', '/conversations/' + conversation.id + '/messages',
    { content: '你好' }), { code: 'model_not_configured', status: 503 });
  assert.equal((await service.request('GET', '/model/config')).api_key, null);
});

test('missing Python executable fails without claiming readiness', async t => {
  const service = await fixture(t, { python: 'becoming-nonexistent-python-executable',
    startupTimeoutMs: 3000 });
  await assert.rejects(service.start(demo), { code: 'service_start_failed' });
  assert.equal(service.running, false);
  await service.stop();
});

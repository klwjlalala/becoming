const form = document.getElementById('config');
const status = document.getElementById('status');
const modelStatus = document.getElementById('model-status');
const persist = form.elements.persist;
let busy = false;
async function refresh() {
  const health = await window.becoming.health();
  status.textContent = health.ok ? '本地服务已连接 · API V' + health.result.api_version : '服务不可用：' + health.error.code;
  const model = await window.becoming.modelStatus();
  if (model.ok) {
    form.elements.base_url.value = model.result.base_url || '';
    form.elements.model.value = model.result.model || '';
    persist.disabled = !model.result.secure_storage_available;
    persist.checked = model.result.saved && !persist.disabled;
    modelStatus.textContent = (model.result.configured ? '模型已配置' : '模型尚未配置') +
      (persist.disabled ? ' · 系统安全存储不可用，仅支持本次会话' : '') +
      (model.result.storage_error ? ' · ' + model.result.storage_error : '');
  }
}
async function apply(testOnly) {
  if (busy || !form.reportValidity()) return;
  busy = true;
  const data = { base_url: form.elements.base_url.value, model: form.elements.model.value,
    api_key: form.elements.api_key.value, persist: persist.checked && !persist.disabled };
  modelStatus.textContent = '正在连接模型…';
  try {
    const result = await (testOnly ? window.becoming.modelTest(data) : window.becoming.modelConfigure(data));
    if (!result.ok) modelStatus.textContent = '操作失败：' + result.error.code;
    else if (testOnly) modelStatus.textContent = '连接测试成功';
    else {
      form.elements.api_key.value = '';
      await refresh();
      modelStatus.textContent = result.result.persisted ? '配置已应用并安全保存' :
        '配置已应用，本次会话有效' + (result.result.storage_error ? ' · 保存失败' : '');
    }
  } catch { modelStatus.textContent = '连接服务失败'; }
  finally { busy = false; }
}
document.getElementById('refresh').addEventListener('click', () => refresh().catch(() => { status.textContent = '服务不可用'; }));
document.getElementById('test').addEventListener('click', () => apply(true));
form.addEventListener('submit', event => { event.preventDefault(); apply(false); });
refresh().catch(() => { status.textContent = '服务不可用'; });

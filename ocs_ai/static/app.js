let config;
const element = id => document.getElementById(id);
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...options.headers, Authorization: config[0].headers.Authorization}});
  const data = await response.json();
  if (!response.ok || data.code !== 0) throw new Error(data.msg || '请求失败');
  return data;
}
async function refresh() {
  const container = element('logs');
  try {
    const {data} = await api('/api/logs');
    container.replaceChildren();
    if (!data.length) {container.textContent = '还没有搜题记录。'; return;}
    for (const log of data) {
      const detail = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `${new Date(log.created * 1000).toLocaleString()} · ${log.cached ? '缓存' : log.status === 'ok' ? '模型' : '失败'} · ${(log.question || '').slice(0,100)}`;
      const body = document.createElement('pre');
      body.textContent = log.status === 'ok' ? `题目：${log.question}\n选项：\n${log.options || ''}\n\n答案：${log.answers.join(' / ')}\n依据：${log.reason}\n耗时：${log.latency_ms} ms\n用量：${JSON.stringify(log.usage)}` : log.msg;
      detail.append(summary, body); container.append(detail);
    }
  } catch (error) {container.textContent = error.message;}
}
element('copy').addEventListener('click', async () => {
  try {await navigator.clipboard.writeText(JSON.stringify(config, null, 2)); element('copy-status').textContent = '已复制';}
  catch {element('copy-status').textContent = '复制失败，请打开 JSON 手动复制。';}
});
element('refresh').addEventListener('click', refresh);
element('clear').addEventListener('click', async () => {
  try {await api('/api/cache', {method:'DELETE'}); element('answer').textContent = '缓存已清空，下次搜题会重新请求模型。';}
  catch(error) {element('answer').textContent = error.message;}
});
element('quiz').addEventListener('submit', async event => {
  event.preventDefault(); element('submit').disabled = true; element('answer').textContent = '正在搜题…';
  try {
    const {data} = await api('/api/search', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:element('title').value,options:element('options').value,type:element('type').value})});
    element('answer').textContent = `答案：${data.answers.join(' / ')}\n依据：${data.reason}\n${data.cached ? '缓存命中' : data.model} · ${data.latency_ms} ms`;
  } catch(error) {element('answer').textContent = error.message;}
  finally {element('submit').disabled = false; await refresh();}
});
async function init() {
  try {
    const health = await (await fetch('/api/health')).json();
    config = await (await fetch('/ocs-config.json')).json();
    element('status').textContent = `${health.configured ? '服务就绪' : '请在 .env 填写 LLM_API_KEY 并重启'} · ${health.model} · 思考 ${health.thinking} / ${health.effort} · 视觉 ${health.vision ? '开启' : '关闭'}`;
    await refresh();
  } catch(error) {element('status').textContent = `服务连接失败：${error.message}`;}
}
init();

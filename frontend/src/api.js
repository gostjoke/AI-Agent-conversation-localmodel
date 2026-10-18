// Backend API client. 後端 API 呼叫。

export async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

/**
 * Stream assistant events via SSE (fetch + reader, supports abort).
 * 以 SSE 串流助手事件（fetch + reader，可中斷）。
 */
export async function streamChat(body, onEvent, signal) {
  const r = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop();
    for (const p of parts) {
      const line = p.trim();
      if (line.startsWith('data:')) onEvent(JSON.parse(line.slice(5)));
    }
  }
}

import { useEffect, useMemo, useRef, useState } from 'react';
import { Avatar, Badge, Button, Tag, Tooltip, Typography, theme } from 'antd';
import { Bubble, Sender } from '@ant-design/x';
import { ClearOutlined, CloseOutlined, MessageOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import { AiContent, applyEvent } from '../pages/ChatPage.jsx';
import { getJSON, streamChat } from '../api.js';
import { load, save, uid } from '../store.js';

/**
 * Floating avatar (bottom-right) → popup chat. Uses the same agent settings as the Assistant page.
 * 右下角浮動頭像 → 彈出對話框；與助手頁共用 agent 設定（模型、工具、提示詞）。
 */
export default function ChatWidget({ dark }) {
  const { token } = theme.useToken();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState(() => load('widget.msgs', []));
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [unread, setUnread] = useState(false);
  const [tools, setTools] = useState([]);
  const [defaultModel, setDefaultModel] = useState('');
  const abortRef = useRef(null);
  const openRef = useRef(open);
  openRef.current = open;

  useEffect(() => { if (!loading) save('widget.msgs', msgs); }, [msgs, loading]);
  useEffect(() => {
    getJSON('/api/tools').then((r) => setTools(r.tools)).catch(() => {});
    getJSON('/api/models').then((r) => setDefaultModel(r.default_assistant)).catch(() => {});
  }, []);
  useEffect(() => {
    if (open) setUnread(false);
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const toolLabels = useMemo(() => Object.fromEntries(tools.map((t) => [t.name, t.label])), [tools]);
  const settings = load('chat.settings', {}); // shared with Assistant page 與助手頁共用

  const send = async (text) => {
    const t = text.trim();
    if (!t || loading) return;
    setInput('');
    const history = [...msgs, { id: uid(), role: 'user', content: t, status: 'success' }];
    const ai = { id: uid(), role: 'assistant', content: '', thinking: '', tools: [], notices: [], status: 'loading' };
    setMsgs([...history, ai]);
    const patch = (fn) => setMsgs((l) => (l.length ? [...l.slice(0, -1), fn(l[l.length - 1])] : l));
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    try {
      await streamChat({
        messages: history.filter((m) => m.status !== 'error' && m.content).map(({ role, content }) => ({ role, content })),
        model: settings.model || null,
        system_prompt: settings.systemPrompt ?? null,
        tools: settings.tools ?? null,
        think: !!settings.think,
        temperature: settings.temperature ?? 0.7,
      }, (ev) => patch((m) => applyEvent(m, ev)), ctrl.signal);
      patch((m) => (m.status === 'error' ? m : { ...m, status: 'success' }));
    } catch (e) {
      patch((m) => (e.name === 'AbortError' ? { ...m, status: 'abort' } : { ...m, status: 'error', error: String(e.message || e) }));
    } finally {
      setLoading(false);
      if (!openRef.current) setUnread(true); // reply arrived while closed 關閉時收到回覆
    }
  };

  const items = msgs.map((m) => ({ key: m.id, role: m.role === 'user' ? 'user' : 'ai', content: m, status: m.status, loading: m.status === 'loading' }));
  const roles = {
    user: { placement: 'end', avatar: <Avatar size="small" icon={<UserOutlined />} />, contentRender: (m) => <div className="user-text">{m.content}</div> },
    ai: { placement: 'start', variant: 'borderless', avatar: <Avatar size="small" className="ai-avatar" icon={<RobotOutlined />} />,
      contentRender: (m) => <AiContent m={m} toolLabels={toolLabels} dark={dark} /> },
  };

  return (
    <>
      {open && (
        <div
          className="cw-panel"
          role="dialog"
          aria-label="AI chat"
          style={{ background: token.colorBgElevated, boxShadow: token.boxShadowSecondary, borderColor: token.colorBorderSecondary }}
        >
          <div className="cw-header" style={{ borderColor: token.colorBorderSecondary }}>
            <Avatar className="ai-avatar" icon={<RobotOutlined />} />
            <div className="cw-title">
              <Typography.Text strong>Will Hsu AI assistant</Typography.Text>
              <Tag color="purple" className="cw-model">{settings.model || defaultModel || 'local'}</Tag>
            </div>
            <Tooltip title="清除對話 Clear">
              <Button type="text" size="small" icon={<ClearOutlined />} disabled={loading || !msgs.length} onClick={() => setMsgs([])} />
            </Tooltip>
            <Tooltip title="關閉 Close (Esc)">
              <Button type="text" size="small" icon={<CloseOutlined />} onClick={() => setOpen(false)} />
            </Tooltip>
          </div>

          <div className="cw-body">
            {msgs.length === 0 ? (
              <div className="cw-empty">
                <Avatar size={48} className="ai-avatar" icon={<RobotOutlined />} />
                <Typography.Text>有什麼可以幫你？</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>How can I help? · 本地模型 Local model</Typography.Text>
              </div>
            ) : (
              <Bubble.List className="cw-list" items={items} role={roles} autoScroll />
            )}
          </div>

          <div className="cw-sender">
            <Sender
              value={input}
              onChange={setInput}
              onSubmit={send}
              loading={loading}
              onCancel={() => abortRef.current?.abort()}
              placeholder="輸入訊息… Ask anything"
              autoSize={{ minRows: 1, maxRows: 4 }}
            />
          </div>
        </div>
      )}

      <Tooltip title={open ? '' : '和 AI 對話 Chat with AI'} placement="left">
        <button className={`cw-fab ${open ? 'open' : ''}`} onClick={() => setOpen(!open)} aria-label="Toggle AI chat">
          <Badge dot={unread} offset={[-4, 4]}>
            <Avatar size={56} className="ai-avatar cw-fab-avatar" icon={open ? <CloseOutlined /> : <RobotOutlined />} />
          </Badge>
          {!open && <span className="cw-fab-hint"><MessageOutlined /></span>}
        </button>
      </Tooltip>
    </>
  );
}

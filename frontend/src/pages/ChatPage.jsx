import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Avatar, Button, Drawer, Grid, Input, Modal, Space, Tag, Tooltip, Typography, message } from 'antd';
import { Bubble, Conversations, Prompts, Sender, Think, ThoughtChain, Welcome } from '@ant-design/x';
import {
  CalculatorOutlined, ClockCircleOutlined, CopyOutlined, DeleteOutlined, EditOutlined,
  FileSearchOutlined, MenuOutlined, PlusOutlined, RedoOutlined, RobotOutlined,
  SettingOutlined, ToolOutlined, UserOutlined,
} from '@ant-design/icons';
import MarkdownView from '../components/MarkdownView.jsx';
import SettingsDrawer from '../components/SettingsDrawer.jsx';
import { getJSON, streamChat } from '../api.js';
import { load, save, uid } from '../store.js';

const DEFAULT_SETTINGS = { model: null, think: false, temperature: 0.7, tools: null, systemPrompt: null };

const PROMPTS = [
  { key: 'p1', icon: <ClockCircleOutlined />, label: '現在幾點？', description: 'What time is it? (tool: time)' },
  { key: 'p2', icon: <CalculatorOutlined />, label: '1250 pcs × $0.85，再加 9.375% 稅是多少？', description: 'Exact math (tool: calculator)' },
  { key: 'p3', icon: <FileSearchOutlined />, label: '列出 workspace 的檔案並摘要內容', description: 'Read files (tools: list/read)' },
  { key: 'p4', icon: <ToolOutlined />, label: '查詢：找出最近 30 天未結的 PO', description: 'Code / SQL help' },
  { key: 'p5', icon: <ToolOutlined />, label: '查詢：找出最近 30 天未結的 WO', description: 'Code / SQL help' },
  { key: 'p6', icon: <ToolOutlined />, label: '查詢：找出最近 30 天未結的 Serial Number', description: 'Code / SQL help' },
];

// Reduce one stream event into the AI message. 將串流事件合併到 AI 訊息。
export function applyEvent(m, ev) {
  switch (ev.type) {
    case 'thinking': return { ...m, status: 'updating', thinking: m.thinking + ev.delta };
    case 'token': return { ...m, status: 'updating', content: m.content + ev.delta };
    case 'tool_start': return { ...m, status: 'updating', tools: [...m.tools, { id: ev.id, name: ev.name, args: ev.args }] };
    case 'tool_end': return { ...m, tools: m.tools.map((t) => (t.id === ev.id ? { ...t, result: ev.result } : t)) };
    case 'notice': return { ...m, notices: [...m.notices, ev.message] };
    case 'error': return { ...m, status: 'error', error: ev.message };
    case 'done': return { ...m, status: 'success' };
    default: return m;
  }
}

export function AiContent({ m, toolLabels, dark }) {
  const busy = m.status === 'loading' || m.status === 'updating';
  return (
    <div className="ai-content">
      {m.notices.map((n, i) => <Alert key={i} type="info" showIcon title={n} className="notice" />)}
      {m.thinking && (
        <Think title={busy && !m.content ? '思考中… Thinking' : '思考過程 Reasoning'} loading={busy && !m.content}>
          <div className="think-text">{m.thinking}</div>
        </Think>
      )}
      {m.tools.length > 0 && (
        <ThoughtChain
          className="tool-chain"
          items={m.tools.map((t) => ({
            key: t.id,
            icon: <ToolOutlined />,
            title: toolLabels[t.name] || t.name,
            description: <Typography.Text type="secondary" code>{JSON.stringify(t.args)}</Typography.Text>,
            status: t.result == null ? 'loading' : t.result.startsWith('Error') ? 'error' : 'success',
            collapsible: t.result != null,
            content: t.result != null && <pre className="tool-result">{t.result}</pre>,
          }))}
        />
      )}
      {m.content && <MarkdownView dark={dark}>{m.content}</MarkdownView>}
      {m.status === 'error' && <Alert type="error" showIcon title={m.error || '發生錯誤 Error'} />}
      {m.status === 'abort' && <Typography.Text type="secondary">（已停止 Stopped）</Typography.Text>}
    </div>
  );
}

export default function ChatPage({ dark }) {
  const screens = Grid.useBreakpoint();
  const [convs, setConvs] = useState(() => load('chat.convs', []));
  const [msgs, setMsgs] = useState(() => load('chat.msgs', {}));
  const [activeKey, setActiveKey] = useState(() => load('chat.active', null));
  const [settings, setSettings] = useState(() => ({ ...DEFAULT_SETTINGS, ...load('chat.settings', {}) }));
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState([]);
  const [tools, setTools] = useState([]);
  const [defaults, setDefaults] = useState({ model: '', systemPrompt: '', workspace: '' });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [renaming, setRenaming] = useState(null);
  const abortRef = useRef(null);

  // Persist (skip while streaming to avoid per-token writes). 串流中不寫入，避免每個 token 都存。
  useEffect(() => { if (!loading) save('chat.msgs', msgs); }, [msgs, loading]);
  useEffect(() => save('chat.convs', convs), [convs]);
  useEffect(() => save('chat.active', activeKey), [activeKey]);
  useEffect(() => save('chat.settings', settings), [settings]);

  useEffect(() => {
    getJSON('/api/models').then((r) => {
      setModels(r.models);
      setDefaults((d) => ({ ...d, model: r.default_assistant }));
    }).catch(() => {});
    getJSON('/api/tools').then((r) => {
      setTools(r.tools);
      setDefaults((d) => ({ ...d, systemPrompt: r.default_system_prompt, workspace: r.workspace }));
    }).catch(() => {});
  }, []);

  const toolLabels = useMemo(() => Object.fromEntries(tools.map((t) => [t.name, t.label])), [tools]);
  const list = msgs[activeKey] || [];
  const model = settings.model || defaults.model;

  const newConv = (title = '新對話 New chat') => {
    const key = uid();
    setConvs((c) => [{ key, label: title, updatedAt: Date.now() }, ...c]);
    setMsgs((p) => ({ ...p, [key]: [] }));
    setActiveKey(key);
    setNavOpen(false);
    return key;
  };

  const removeConv = (key) => {
    setConvs((c) => c.filter((x) => x.key !== key));
    setMsgs(({ [key]: _, ...rest }) => rest);
    if (key === activeKey) setActiveKey(null);
  };

  const run = async (key, history) => {
    const ai = { id: uid(), role: 'assistant', content: '', thinking: '', tools: [], notices: [], status: 'loading' };
    setMsgs((p) => ({ ...p, [key]: [...history, ai] }));
    const patch = (fn) => setMsgs((p) => {
      const l = p[key];
      if (!l?.length) return p;
      return { ...p, [key]: [...l.slice(0, -1), fn(l[l.length - 1])] };
    });
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    try {
      await streamChat({
        messages: history.filter((m) => m.status !== 'error' && m.content).map(({ role, content }) => ({ role, content })),
        model,
        system_prompt: settings.systemPrompt,
        tools: settings.tools,
        think: settings.think,
        temperature: settings.temperature,
      }, (ev) => patch((m) => applyEvent(m, ev)), ctrl.signal);
      patch((m) => (m.status === 'error' ? m : { ...m, status: 'success' }));
    } catch (e) {
      patch((m) => (e.name === 'AbortError' ? { ...m, status: 'abort' } : { ...m, status: 'error', error: String(e.message || e) }));
    } finally {
      setLoading(false);
      setConvs((c) => c.map((x) => (x.key === key ? { ...x, updatedAt: Date.now() } : x)));
    }
  };

  const send = (text) => {
    const t = text.trim();
    if (!t || loading) return;
    let key = activeKey && msgs[activeKey] ? activeKey : null;
    if (!key) key = newConv(t.slice(0, 24));
    else if (!list.length) setConvs((c) => c.map((x) => (x.key === key ? { ...x, label: t.slice(0, 24) } : x)));
    setInput('');
    run(key, [...(msgs[key] || []), { id: uid(), role: 'user', content: t, status: 'success' }]);
  };

  const regenerate = () => {
    if (loading || !list.length) return;
    const lastUser = list.map((m) => m.role).lastIndexOf('user');
    if (lastUser >= 0) run(activeKey, list.slice(0, lastUser + 1));
  };

  const items = list.map((m, i) => ({
    key: m.id,
    role: m.role === 'user' ? 'user' : 'ai',
    content: m,
    status: m.status,
    loading: m.status === 'loading',
    extraInfo: { isLast: i === list.length - 1 },
  }));

  const roles = {
    user: {
      placement: 'end',
      avatar: <Avatar icon={<UserOutlined />} />,
      contentRender: (m) => <div className="user-text">{m.content}</div>,
    },
    ai: (data) => ({
      placement: 'start',
      variant: 'borderless',
      avatar: <Avatar className="ai-avatar" icon={<RobotOutlined />} />,
      contentRender: (m) => <AiContent m={m} toolLabels={toolLabels} dark={dark} />,
      footer: (m) => (m.status === 'loading' || m.status === 'updating' ? null : (
        <Space size={0}>
          <Tooltip title="複製 Copy">
            <Button size="small" type="text" icon={<CopyOutlined />}
              onClick={() => navigator.clipboard?.writeText(m.content).then(() => message.success('已複製 Copied'))} />
          </Tooltip>
          {data.extraInfo?.isLast && (
            <Tooltip title="重新產生 Regenerate">
              <Button size="small" type="text" icon={<RedoOutlined />} onClick={regenerate} />
            </Tooltip>
          )}
        </Space>
      )),
    }),
  };

  const nav = (
    <div className="conv-nav">
      <Button block type="primary" ghost icon={<PlusOutlined />} onClick={() => newConv()} disabled={loading}>
        新對話 New chat
      </Button>
      <Conversations
        className="conv-list"
        items={[...convs].sort((a, b) => b.updatedAt - a.updatedAt).map(({ key, label }) => ({ key, label }))}
        activeKey={activeKey}
        onActiveChange={(k) => { if (!loading) { setActiveKey(k); setNavOpen(false); } }}
        menu={(conv) => ({
          items: [
            { key: 'rename', label: '重新命名 Rename', icon: <EditOutlined /> },
            { key: 'delete', label: '刪除 Delete', icon: <DeleteOutlined />, danger: true },
          ],
          onClick: ({ key, domEvent }) => {
            domEvent?.stopPropagation();
            if (key === 'delete') removeConv(conv.key);
            else setRenaming({ key: conv.key, label: convs.find((c) => c.key === conv.key)?.label || '' });
          },
        })}
      />
    </div>
  );

  return (
    <div className="chat-page">
      {screens.md ? <aside className="chat-sider">{nav}</aside> : (
        <Drawer placement="left" open={navOpen} onClose={() => setNavOpen(false)} size={280} title="對話 Chats">{nav}</Drawer>
      )}

      <section className="chat-main">
        <div className="chat-toolbar">
          {!screens.md && <Button type="text" icon={<MenuOutlined />} onClick={() => setNavOpen(true)} />}
          <Tag color="purple">{model || '未選模型 no model'}</Tag>
          {settings.think && <Tag color="gold">Thinking</Tag>}
          <Tag>{settings.tools ? `${settings.tools.length} tools` : 'all tools'}</Tag>
          <Button type="text" icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)} style={{ marginLeft: 'auto' }}>
            設定 Settings
          </Button>
        </div>

        <div className="chat-scroll">
          {list.length === 0 ? (
            <div className="welcome-wrap">
              <Welcome
                variant="borderless"
                icon={<Avatar size={56} className="ai-avatar" icon={<RobotOutlined />} />}
                title="你好，我是 Will Hsu AI assistant"
                description="Runs 100% on a local model — 會使用工具（時間、計算、讀寫沙盒檔案），資料不離開你的電腦。"
              />
              <Prompts
                title="試試看 Try:"
                wrap
                items={PROMPTS}
                onItemClick={({ data }) => send(data.label)}
                styles={{ item: { flex: '1 1 calc(50% - 8px)' } }}
              />
            </div>
          ) : (
            <Bubble.List className="bubble-list" items={items} role={roles} autoScroll />
          )}
        </div>

        <div className="chat-sender">
          <Sender
            value={input}
            onChange={setInput}
            onSubmit={send}
            loading={loading}
            onCancel={() => abortRef.current?.abort()}
            placeholder="輸入訊息，Enter 送出 / Shift+Enter 換行  ·  Ask anything…"
            autoSize={{ minRows: 1, maxRows: 8 }}
          />
          <Typography.Text type="secondary" className="hint">本地模型可能出錯，重要資訊請再確認 · Local models can be wrong.</Typography.Text>
        </div>
      </section>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings}
        onChange={setSettings}
        models={models}
        tools={tools}
        defaults={defaults}
      />

      <Modal
        title="重新命名 Rename"
        open={!!renaming}
        onCancel={() => setRenaming(null)}
        onOk={() => {
          setConvs((c) => c.map((x) => (x.key === renaming.key ? { ...x, label: renaming.label || x.label } : x)));
          setRenaming(null);
        }}
      >
        <Input value={renaming?.label} onChange={(e) => setRenaming({ ...renaming, label: e.target.value })} autoFocus />
      </Modal>
    </div>
  );
}

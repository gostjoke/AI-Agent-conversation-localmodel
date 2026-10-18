import { useEffect, useRef, useState } from 'react';
import { Alert, Avatar, Button, Divider, Input, InputNumber, Select, Space, Typography } from 'antd';
import { Bubble } from '@ant-design/x';
import { PlayCircleOutlined, StopOutlined } from '@ant-design/icons';
import MarkdownView from '../components/MarkdownView.jsx';
import { getJSON } from '../api.js';

// 3-agent debate over WebSocket. 三位 agent 透過 WebSocket 辯論。
export default function DebatePage() {
  const [topic, setTopic] = useState('');
  const [rounds, setRounds] = useState(2);
  const [model, setModel] = useState(null);
  const [models, setModels] = useState([]);
  const [turns, setTurns] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const wsRef = useRef(null);

  useEffect(() => {
    getJSON('/api/models').then((r) => { setModels(r.models); setModel((m) => m || r.default_debate); }).catch(() => {});
    return () => wsRef.current?.close();
  }, []);

  const start = () => {
    if (!topic.trim()) return;
    setTurns([]); setError(null); setRunning(true);
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/conversation`);
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ topic, rounds, model }));
    ws.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === 'round') setTurns((t) => [...t, { key: `r${ev.round}`, divider: `Round ${ev.round} / ${ev.total}` }]);
      if (ev.type === 'agent_start') setTurns((t) => [...t, { key: `${ev.agent_id}-${ev.round}`, agent: ev, content: '', done: false }]);
      if (ev.type === 'token') setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, content: x.content + ev.token } : x)));
      if (ev.type === 'agent_done') setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, done: true } : x)));
      if (ev.type === 'error') setError(ev.message);
      if (ev.type === 'done' || ev.type === 'error') { setRunning(false); ws.close(); }
    };
    ws.onerror = () => { setError('WebSocket 連線失敗 connection failed — backend running?'); setRunning(false); };
    ws.onclose = () => setRunning(false);
  };

  const stop = () => { wsRef.current?.close(); setRunning(false); };

  return (
    <div className="debate-page">
      <Space.Compact block className="debate-form">
        <Input
          size="large"
          placeholder="辯論主題 Topic, e.g. 工廠是否該全面導入 AI 排程？"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onPressEnter={start}
          disabled={running}
        />
        <InputNumber size="large" min={1} max={10} value={rounds} onChange={setRounds} disabled={running} prefix="回合" style={{ width: 110 }} />
        <Select size="large" value={model} onChange={setModel} disabled={running} style={{ width: 180 }}
          options={models.map((m) => ({ value: m.name, label: m.name }))} />
        {running
          ? <Button size="large" danger icon={<StopOutlined />} onClick={stop}>停止</Button>
          : <Button size="large" type="primary" icon={<PlayCircleOutlined />} onClick={start}>開始 Start</Button>}
      </Space.Compact>

      {error && <Alert type="error" showIcon title={error} style={{ margin: '12px 0' }} />}

      <div className="debate-list">
        {turns.length === 0 && !error && (
          <Typography.Paragraph type="secondary" style={{ textAlign: 'center', marginTop: 48 }}>
            Alex（樂觀派）、Jordan（懷疑派）、Morgan（務實派）會輪流針對主題發言。
          </Typography.Paragraph>
        )}
        {turns.map((t) => (t.divider ? <Divider key={t.key}>{t.divider}</Divider> : (
          <Bubble
            key={t.key}
            placement="start"
            loading={!t.content}
            avatar={<Avatar style={{ background: t.agent.color }}>{t.agent.avatar}</Avatar>}
            header={<Typography.Text strong style={{ color: t.agent.color }}>{t.agent.name} · {t.agent.role}</Typography.Text>}
            content={t.content}
            contentRender={(c) => <MarkdownView>{c}</MarkdownView>}
            style={{ marginBottom: 12 }}
          />
        )))}
      </div>
    </div>
  );
}

import { useEffect, useState } from 'react';
import { Badge, Button, Layout, Segmented, Space, Tooltip, Typography, theme } from 'antd';
import { XProvider } from '@ant-design/x';
import zhTW from 'antd/locale/zh_TW';
import { MoonOutlined, RobotOutlined, SunOutlined, TeamOutlined } from '@ant-design/icons';
import ChatPage from './pages/ChatPage.jsx';
import DebatePage from './pages/DebatePage.jsx';
import { getJSON } from './api.js';
import { load, save } from './store.js';

export default function App() {
  const [dark, setDark] = useState(() => load('ui.dark', false));
  const [page, setPage] = useState(() => load('ui.page', 'chat'));
  const [health, setHealth] = useState(null);

  useEffect(() => save('ui.dark', dark), [dark]);
  useEffect(() => save('ui.page', page), [page]);
  useEffect(() => {
    const tick = () => getJSON('/health').then(setHealth).catch(() => setHealth(null));
    tick();
    const t = setInterval(tick, 15000);
    return () => clearInterval(t);
  }, []);

  const ok = health?.ollama?.ollama_running;
  const status = !health ? ['error', '後端離線 Backend offline']
    : !ok ? ['warning', 'Ollama 未啟動 offline'] : ['success', 'Ollama 已連線 online'];

  return (
    <XProvider
      locale={zhTW}
      theme={{
        algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: { colorPrimary: '#5b5bd6', borderRadius: 10 },
      }}
    >
      <Layout className={`app ${dark ? 'dark' : ''}`}>
        <Layout.Header className="app-header">
          <Space size={10}>
            <div className="logo"><RobotOutlined /></div>
            <Typography.Text strong style={{ fontSize: 16 }}>Local AI Agent</Typography.Text>
          </Space>
          <Segmented
            value={page}
            onChange={setPage}
            options={[
              { value: 'chat', label: '助手 Assistant', icon: <RobotOutlined /> },
              { value: 'debate', label: '辯論 Debate', icon: <TeamOutlined /> },
            ]}
          />
          <Space>
            <Badge status={status[0]} text={status[1]} />
            <Tooltip title="切換主題 Theme">
              <Button type="text" icon={dark ? <SunOutlined /> : <MoonOutlined />} onClick={() => setDark(!dark)} />
            </Tooltip>
          </Space>
        </Layout.Header>
        <Layout.Content className="app-content">
          {page === 'chat' ? <ChatPage dark={dark} /> : <DebatePage />}
        </Layout.Content>
      </Layout>
    </XProvider>
  );
}

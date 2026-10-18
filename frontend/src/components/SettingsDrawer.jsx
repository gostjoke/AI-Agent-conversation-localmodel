import { Button, Checkbox, Drawer, Form, Input, Select, Slider, Switch, Typography } from 'antd';

// Agent settings: model, prompt, tools, thinking. Agent 設定：模型、提示詞、工具、思考模式。
export default function SettingsDrawer({ open, onClose, settings, onChange, models, tools, defaults }) {
  const set = (patch) => onChange({ ...settings, ...patch });
  const toolNames = tools.map((t) => t.name);
  const selected = settings.tools ?? toolNames; // null = all 全部

  return (
    <Drawer title="Agent 設定 Settings" open={open} onClose={onClose} size={380}>
      <Form layout="vertical">
        <Form.Item label="模型 Model" extra="工具呼叫需支援 tools 的模型，如 qwen3 / llama3.1 / mistral-nemo">
          <Select
            showSearch
            value={settings.model || defaults.model}
            onChange={(model) => set({ model })}
            options={models.map((m) => ({ value: m.name, label: `${m.name}  ${m.params || ''}` }))}
            notFoundContent="沒有模型 — ollama pull qwen3:8b"
          />
        </Form.Item>
        <Form.Item label="思考模式 Thinking" extra="qwen3 / deepseek-r1 會顯示推理過程">
          <Switch checked={settings.think} onChange={(think) => set({ think })} />
        </Form.Item>
        <Form.Item label={`溫度 Temperature: ${settings.temperature}`}>
          <Slider min={0} max={1.5} step={0.1} value={settings.temperature} onChange={(temperature) => set({ temperature })} />
        </Form.Item>
        <Form.Item label="工具 Tools" extra={<>沙盒資料夾 Workspace: <Typography.Text code>{defaults.workspace}</Typography.Text></>}>
          <Checkbox.Group
            style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
            value={selected}
            onChange={(v) => set({ tools: v.length === toolNames.length ? null : v })}
            options={tools.map((t) => ({ value: t.name, label: t.label }))}
          />
        </Form.Item>
        <Form.Item label="系統提示詞 System prompt">
          <Input.TextArea
            autoSize={{ minRows: 4, maxRows: 12 }}
            value={settings.systemPrompt ?? defaults.systemPrompt}
            onChange={(e) => set({ systemPrompt: e.target.value })}
          />
          <Button size="small" type="link" style={{ paddingLeft: 0 }} onClick={() => set({ systemPrompt: null })}>
            還原預設 Reset
          </Button>
        </Form.Item>
      </Form>
    </Drawer>
  );
}

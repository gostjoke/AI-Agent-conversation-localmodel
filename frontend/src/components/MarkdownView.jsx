import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeHighlighter } from '@ant-design/x';

// Markdown + GFM tables + highlighted code. Markdown 渲染（表格、程式碼高亮）。
export default function MarkdownView({ children, dark }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children: code, ...rest }) {
            const lang = /language-(\w+)/.exec(className || '')?.[1];
            const text = String(code).replace(/\n$/, '');
            if (!lang && !text.includes('\n')) return <code className="inline" {...rest}>{code}</code>;
            return <CodeHighlighter lang={lang || 'text'} prismLightMode={!dark}>{text}</CodeHighlighter>;
          },
          pre: ({ children: c }) => <>{c}</>,
          a: (p) => <a {...p} target="_blank" rel="noreferrer" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

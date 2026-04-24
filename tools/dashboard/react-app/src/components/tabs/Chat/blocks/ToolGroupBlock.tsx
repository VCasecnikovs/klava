import { ToolUseBlock } from './ToolUseBlock';
import type { Block } from '@/context/ChatContext';

export function ToolGroupBlock({ block }: { block: Block }) {
  const tools = block.tools || [];

  return (
    <div className="chat-tool-group">
      <span className="chat-tool-group-label">{tools.length} parallel calls</span>
      {tools.map((t, i) => (
        <ToolUseBlock key={i} block={{ ...t, id: block.id * 1000 + i }} />
      ))}
    </div>
  );
}

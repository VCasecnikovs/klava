import type { Block } from '@/context/ChatContext';
import { UserBlock } from './UserBlock';
import { AssistantBlock } from './AssistantBlock';
import { StreamingBlock } from './StreamingBlock';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolUseBlock } from './ToolUseBlock';
import { ToolGroupBlock } from './ToolGroupBlock';
import { ToolResultBlock } from './ToolResultBlock';
import { AgentBlock } from './AgentBlock';
import { QuestionBlock } from './QuestionBlock';
import { CostBlock } from './CostBlock';
import { ErrorBlock } from './ErrorBlock';
import { CompactionBlock } from './CompactionBlock';
import { RateLimitBlock } from './RateLimitBlock';
// LoadingBlock removed - replaced by SpinnerBar above input

interface BlockRendererProps {
  block: Block;
  isStreaming?: boolean;
  isLast?: boolean;
}

export function BlockRenderer({ block, isStreaming, isLast }: BlockRendererProps) {
  if (block.type === '_removed') return null;

  // Use StreamingBlock for the last assistant block during active streaming
  if (isStreaming && isLast && block.type === 'assistant') {
    return <StreamingBlock block={block} />;
  }

  switch (block.type) {
    case 'user':
      return <UserBlock block={block} />;
    case 'assistant':
      return <AssistantBlock block={block} />;
    case 'thinking':
      return <ThinkingBlock block={block} />;
    case 'tool_use':
      return <ToolUseBlock block={block} />;
    case 'tool_group':
      return <ToolGroupBlock block={block} />;
    case 'agent':
      return <AgentBlock block={block} />;
    case 'tool_result':
      return <ToolResultBlock block={block} />;
    case 'question':
      return <QuestionBlock block={block} />;
    case 'cost':
      return <CostBlock block={block} />;
    case 'error':
      return <ErrorBlock block={block} />;
    case 'compaction':
      return <CompactionBlock block={block} />;
    case 'rate_limit':
      return <RateLimitBlock block={block} />;
    case 'loading':
      return null; // Visual indicator moved to SpinnerBar
    case 'plan': {
      return (
        <div className={`chat-plan-banner${block.active ? '' : ' chat-plan-banner-ready'}`}>
          <div className="chat-plan-banner-icon">
            {block.active ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z" />
                <path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            )}
          </div>
          <div className="chat-plan-banner-text">
            {block.active ? 'Entered Plan Mode' : 'Plan Ready for Review'}
          </div>
          <div className="chat-plan-banner-hint">
            {block.active ? 'Claude is drafting a plan before executing' : 'Plan was presented above - review and respond to proceed'}
          </div>
        </div>
      );
    }
    default:
      return null;
  }
}

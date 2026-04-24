import { renderChatMD } from '../ChatMarkdown';
import type { ArtifactRef } from './types';

export type ArtifactSegment =
  | { type: 'markdown'; html: string }
  | { type: 'artifact'; ref: ArtifactRef };

/**
 * Check if text contains any ```artifact code fences.
 */
export function hasArtifact(text: string): boolean {
  return text.includes('```artifact');
}

/**
 * Split assistant text into markdown and artifact segments.
 * Detects ```artifact ... ``` code fences and parses JSON inside.
 */
export function parseArtifactContent(text: string): ArtifactSegment[] {
  const segments: ArtifactSegment[] = [];
  const regex = /```artifact\s*\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    // Markdown before this artifact block
    if (match.index > lastIndex) {
      const mdText = text.slice(lastIndex, match.index);
      if (mdText.trim()) {
        segments.push({ type: 'markdown', html: renderChatMD(mdText) });
      }
    }

    // Try parsing artifact JSON
    const jsonStr = match[1].trim();
    try {
      const parsed = JSON.parse(jsonStr);
      if (parsed.filename || parsed.path) {
        segments.push({
          type: 'artifact',
          ref: {
            filename: parsed.filename,
            path: parsed.path,
            title: parsed.title || parsed.filename || parsed.path,
          },
        });
      } else {
        // Invalid - render as code block
        segments.push({ type: 'markdown', html: renderChatMD(text.slice(match.index, match.index + match[0].length)) });
      }
    } catch {
      // Invalid JSON - fall back to code block
      segments.push({ type: 'markdown', html: renderChatMD(text.slice(match.index, match.index + match[0].length)) });
    }

    lastIndex = match.index + match[0].length;
  }

  // Remaining markdown
  if (lastIndex < text.length) {
    const mdText = text.slice(lastIndex);
    if (mdText.trim()) {
      segments.push({ type: 'markdown', html: renderChatMD(mdText) });
    }
  }

  if (segments.length === 0 && text.trim()) {
    segments.push({ type: 'markdown', html: renderChatMD(text) });
  }

  return segments;
}

/**
 * Extract all artifact refs from text (for sidebar tracking).
 */
export function extractArtifactRefs(text: string): ArtifactRef[] {
  const refs: ArtifactRef[] = [];
  const regex = /```artifact\s*\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    try {
      const parsed = JSON.parse(match[1].trim());
      if (parsed.filename || parsed.path) {
        refs.push({
          filename: parsed.filename,
          path: parsed.path,
          title: parsed.title || parsed.filename || parsed.path,
        });
      }
    } catch {
      // skip invalid
    }
  }

  return refs;
}

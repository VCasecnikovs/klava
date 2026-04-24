import { describe, it, expect } from 'vitest';
import { renderChatMD } from '@/components/tabs/Chat/ChatMarkdown';

describe('renderChatMD', () => {
  // ---- Inline formatting ----
  describe('inline formatting', () => {
    it('renders bold text', () => {
      expect(renderChatMD('**bold**')).toContain('<strong>bold</strong>');
    });

    it('renders italic text', () => {
      expect(renderChatMD('*italic*')).toContain('<em>italic</em>');
    });

    it('renders inline code', () => {
      expect(renderChatMD('use `npm test`')).toContain('<code>npm test</code>');
    });

    it('renders combined formatting', () => {
      const result = renderChatMD('**bold** and *italic* and `code`');
      expect(result).toContain('<strong>bold</strong>');
      expect(result).toContain('<em>italic</em>');
      expect(result).toContain('<code>code</code>');
    });

    it('escapes HTML entities in text', () => {
      const result = renderChatMD('a < b & c > d');
      expect(result).toContain('&lt;');
      expect(result).toContain('&amp;');
      expect(result).toContain('&gt;');
    });
  });

  // ---- Code blocks ----
  describe('code blocks', () => {
    it('renders fenced code blocks', () => {
      const result = renderChatMD('```\nconst x = 1;\n```');
      expect(result).toContain('<pre><code>');
      expect(result).toContain('const x = 1;');
      expect(result).toContain('chat-code-block');
    });

    it('renders code blocks with language label', () => {
      const result = renderChatMD('```typescript\nconst x: number = 1;\n```');
      expect(result).toContain('chat-code-lang');
      expect(result).toContain('typescript');
    });

    it('escapes HTML inside code blocks', () => {
      const result = renderChatMD('```\n<div>test</div>\n```');
      expect(result).toContain('&lt;div&gt;');
    });

    it('handles unclosed code blocks', () => {
      const result = renderChatMD('```\ncode without closing');
      expect(result).toContain('code without closing');
      expect(result).toContain('chat-code-block');
    });
  });

  // ---- Headings ----
  describe('headings', () => {
    it('renders h1 as h2', () => {
      const result = renderChatMD('# Title');
      expect(result).toContain('<h2>');
      expect(result).toContain('Title');
    });

    it('renders h2', () => {
      const result = renderChatMD('## Section');
      expect(result).toContain('<h2>');
      expect(result).toContain('Section');
    });

    it('renders h3', () => {
      const result = renderChatMD('### Subsection');
      expect(result).toContain('<h3>');
      expect(result).toContain('Subsection');
    });

    it('applies inline formatting in headings', () => {
      const result = renderChatMD('## **Bold** heading');
      expect(result).toContain('<strong>Bold</strong>');
      expect(result).toContain('<h2>');
    });
  });

  // ---- Lists ----
  describe('lists', () => {
    it('renders unordered lists with dash', () => {
      const result = renderChatMD('- item 1\n- item 2');
      expect(result).toContain('<ul>');
      expect(result).toContain('<li>item 1</li>');
      expect(result).toContain('<li>item 2</li>');
    });

    it('renders unordered lists with asterisk', () => {
      const result = renderChatMD('* item 1\n* item 2');
      expect(result).toContain('<ul>');
      expect(result).toContain('<li>item 1</li>');
    });

    it('renders ordered lists', () => {
      const result = renderChatMD('1. first\n2. second');
      expect(result).toContain('<ul>');
      expect(result).toContain('<li>first</li>');
      expect(result).toContain('<li>second</li>');
    });

    it('applies inline formatting in list items', () => {
      const result = renderChatMD('- **bold** item');
      expect(result).toContain('<strong>bold</strong>');
    });
  });

  // ---- Links ----
  describe('links', () => {
    it('renders http links', () => {
      const result = renderChatMD('[Click](http://example.com)');
      expect(result).toContain('href="http://example.com"');
      expect(result).toContain('>Click<');
    });

    it('renders https links', () => {
      const result = renderChatMD('[Docs](https://docs.example.com)');
      expect(result).toContain('href="https://docs.example.com"');
    });

    it('adds target="_blank" to links', () => {
      const result = renderChatMD('[Link](https://example.com)');
      expect(result).toContain('target="_blank"');
    });

    // Regression: Deck result cards reference artifact URLs as bare URLs,
    // not [label](url) syntax. They must render as clickable anchors.
    it('auto-linkifies bare https URLs', () => {
      const result = renderChatMD('see https://luma.com/2xbmo7a9 for the event');
      expect(result).toContain('<a href="https://luma.com/2xbmo7a9"');
      expect(result).toContain('target="_blank"');
    });

    it('auto-linkifies bare http URLs', () => {
      const result = renderChatMD('fallback http://example.com here');
      expect(result).toContain('<a href="http://example.com"');
    });

    it('does not double-linkify URLs inside markdown link syntax', () => {
      const result = renderChatMD('[Docs](https://docs.example.com)');
      // Exactly one anchor, no nested <a>
      const anchors = (result.match(/<a /g) || []).length;
      expect(anchors).toBe(1);
      expect(result).not.toContain('<a href="https://docs.example.com" target="_blank" style="color:var(--blue)">https://docs.example.com</a>');
    });

    it('strips trailing punctuation from auto-linkified URLs', () => {
      const result = renderChatMD('visit https://example.com.');
      expect(result).toContain('<a href="https://example.com"');
      // The dot should stay outside the anchor
      expect(result).toMatch(/<\/a>\./);
    });

    // Regression: Deck result cards write artifacts like `~/Documents/MyBrain/...`.
    // Those should open in Obsidian via obsidian:// deeplink.
    it('linkifies MyBrain inline-code paths to obsidian:// URI', () => {
      const result = renderChatMD('Updated: `~/Documents/MyBrain/Inbox/2026-04-21 - Trip Logistics.md`');
      expect(result).toContain('href="obsidian://open?vault=MyBrain&file=Inbox%2F2026-04-21%20-%20SF%20Trip%20Logistics"');
      expect(result).toContain('<code>~/Documents/MyBrain/Inbox/2026-04-21 - Trip Logistics.md</code>');
    });

    it('does not linkify non-MyBrain inline code paths', () => {
      const result = renderChatMD('Check `/tmp/foo.txt` for details');
      expect(result).not.toContain('obsidian://');
      expect(result).toContain('<code>/tmp/foo.txt</code>');
    });
  });

  // ---- Security ----
  describe('security', () => {
    it('blocks javascript: URLs in links', () => {
      const result = renderChatMD('[evil](javascript:alert(1))');
      expect(result).not.toContain('href="javascript:');
      expect(result).toContain('evil');
    });

    it('blocks JavaScript: URLs (case insensitive)', () => {
      const result = renderChatMD('[evil](JavaScript:alert(1))');
      expect(result).not.toContain('href=');
    });

    it('blocks data: URLs in links', () => {
      const result = renderChatMD('[evil](data:text/html,<script>)');
      expect(result).not.toContain('href="data:');
    });

    it('allows only http and https schemes', () => {
      const result = renderChatMD('[file](file:///etc/passwd)');
      expect(result).not.toContain('href="file:');
    });
  });

  // ---- Line breaks ----
  describe('line breaks', () => {
    it('renders empty lines as <br>', () => {
      const result = renderChatMD('line 1\n\nline 2');
      expect(result).toContain('<br>');
    });

    it('strips trailing newlines', () => {
      const result = renderChatMD('text\n\n\n');
      expect(result).toBe('text');
    });

    it('adds br between consecutive text lines', () => {
      const result = renderChatMD('line 1\nline 2');
      expect(result).toContain('line 1');
      expect(result).toContain('<br>');
      expect(result).toContain('line 2');
    });
  });

  // ---- Tables ----
  describe('tables', () => {
    it('renders a basic markdown table', () => {
      const md = '| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |';
      const result = renderChatMD(md);
      expect(result).toContain('<table');
      expect(result).toContain('<th>Name</th>');
      expect(result).toContain('<th>Age</th>');
      expect(result).toContain('<td>Alice</td>');
      expect(result).toContain('<td>30</td>');
      expect(result).toContain('<td>Bob</td>');
    });

    it('applies inline formatting in table cells', () => {
      const md = '| Col |\n| --- |\n| **bold** |';
      const result = renderChatMD(md);
      expect(result).toContain('<strong>bold</strong>');
    });

    it('handles tables with text before and after', () => {
      const md = 'Before\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\nAfter';
      const result = renderChatMD(md);
      expect(result).toContain('Before');
      expect(result).toContain('<table');
      expect(result).toContain('After');
    });

    it('handles missing cells gracefully', () => {
      const md = '| A | B | C |\n| - | - | - |\n| 1 |';
      const result = renderChatMD(md);
      expect(result).toContain('<table');
      // Should have 3 td cells even though only 1 value provided
      expect(result).toContain('<td>1</td>');
    });
  });

  // ---- Tables - edge cases ----
  describe('tables - edge cases', () => {
    it('flushes single pipe line as inline text (tableBuf < 2)', () => {
      // A single pipe-delimited line without separator should NOT render as table
      const result = renderChatMD('| just one line |');
      expect(result).not.toContain('<table');
      expect(result).toContain('just one line');
    });

    it('flushes pipe lines without valid separator as inline text', () => {
      // Two pipe lines where the second is NOT a separator row
      const result = renderChatMD('| A | B |\n| not a separator |');
      expect(result).not.toContain('<table');
      expect(result).toContain('A');
    });

    it('handles table at end of input (flush via end-of-lines)', () => {
      const md = '| H1 | H2 |\n| --- | --- |\n| v1 | v2 |';
      const result = renderChatMD(md);
      expect(result).toContain('<table');
      expect(result).toContain('<td>v1</td>');
    });
  });

  // ---- Inline formatting - Telegram HTML tags ----
  describe('telegram HTML tags', () => {
    it('converts escaped <b> tags to <strong>', () => {
      const result = renderChatMD('<b>bold text</b>');
      expect(result).toContain('<strong>bold text</strong>');
    });

    it('converts escaped <i> tags to <em>', () => {
      const result = renderChatMD('<i>italic text</i>');
      expect(result).toContain('<em>italic text</em>');
    });

    it('converts escaped <br> tags', () => {
      const result = renderChatMD('line1<br>line2');
      expect(result).toContain('<br>');
    });

    it('converts self-closing <br/> tags', () => {
      const result = renderChatMD('line1<br/>line2');
      expect(result).toContain('<br>');
    });
  });

  // ---- Edge cases ----
  describe('edge cases', () => {
    it('handles empty string', () => {
      // Empty string splits to [''] which is an empty-trimmed line -> <br>
      expect(renderChatMD('')).toBe('<br>');
    });

    it('handles plain text without formatting', () => {
      expect(renderChatMD('hello world')).toContain('hello world');
    });

    it('does not add br before heading', () => {
      const result = renderChatMD('text\n# Heading');
      expect(result).toContain('text');
      expect(result).toContain('<h2>');
      // Should NOT add <br> before heading
    });

    it('does not add br before code block', () => {
      const result = renderChatMD('text\n```\ncode\n```');
      expect(result).toContain('text');
      expect(result).toContain('chat-code-block');
    });

    it('handles list followed by non-list text', () => {
      const result = renderChatMD('- item1\n- item2\nsome text');
      expect(result).toContain('<ul>');
      expect(result).toContain('some text');
    });
  });
});

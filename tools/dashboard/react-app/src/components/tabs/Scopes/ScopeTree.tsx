import { useMemo, useState } from 'react';

interface Node {
  name: string;
  path: string;       // full scope path including trailing slash
  children: Node[];
  isScope: boolean;   // true if this node is itself in the input list
}

interface Props {
  scopes: string[];
  selected: string | null;
  onSelect: (scope: string) => void;
}

const ACCENT = '#f59e0b';
const HOVER = '#1c1917';

function buildTree(scopes: string[]): Node {
  const root: Node = { name: '', path: '', children: [], isScope: false };
  const known = new Set(scopes);
  for (const scope of scopes) {
    const parts = scope.split('/').filter(Boolean);
    let cur = root;
    let acc = '';
    for (const part of parts) {
      acc += part + '/';
      let child = cur.children.find(c => c.name === part);
      if (!child) {
        child = { name: part, path: acc, children: [], isScope: known.has(acc) };
        cur.children.push(child);
      }
      cur = child;
    }
    // Ensure leaf marked
    cur.isScope = true;
  }
  // Sort: folders with children first (alpha), then leaves alpha.
  const sortRec = (n: Node) => {
    n.children.sort((a, b) => {
      const ach = a.children.length > 0;
      const bch = b.children.length > 0;
      if (ach !== bch) return bch ? 1 : -1;
      return a.name.localeCompare(b.name);
    });
    n.children.forEach(sortRec);
  };
  sortRec(root);
  return root;
}

export function ScopeTree({ scopes, selected, onSelect }: Props) {
  const tree = useMemo(() => buildTree(scopes), [scopes]);
  // Auto-expand top-level so the user sees everything one click in.
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const s = new Set<string>();
    for (const c of tree.children) s.add(c.path);
    return s;
  });

  const toggle = (path: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const renderNode = (n: Node, depth: number): JSX.Element => {
    const isOpen = expanded.has(n.path);
    const hasChildren = n.children.length > 0;
    const isSelected = n.path === selected;
    return (
      <div key={n.path}>
        <div
          onClick={() => {
            if (n.isScope) onSelect(n.path);
            if (hasChildren) toggle(n.path);
          }}
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            padding: '4px 6px', paddingLeft: 6 + depth * 12,
            cursor: 'pointer',
            background: isSelected ? HOVER : 'transparent',
            borderLeft: isSelected ? `2px solid ${ACCENT}` : '2px solid transparent',
            color: isSelected ? '#fafafa' : (n.isScope ? '#d4d4d8' : '#a1a1aa'),
            fontSize: 12,
            fontWeight: isSelected ? 600 : 400,
            userSelect: 'none',
          }}
        >
          <span style={{ width: 10, color: '#52525b', flexShrink: 0 }}>
            {hasChildren ? (isOpen ? '▾' : '▸') : ''}
          </span>
          <span style={{
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{n.name}{n.isScope ? '/' : ''}</span>
        </div>
        {isOpen && hasChildren && (
          <div>
            {n.children.map(c => renderNode(c, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ padding: '6px 0' }}>
      {tree.children.map(c => renderNode(c, 0))}
    </div>
  );
}

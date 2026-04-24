/**
 * MdLink - clickable link that opens an Obsidian markdown file in the Views tab.
 * Usage: <MdLink path="People/John Smith.md" title="John Smith" />
 *        <MdLink path="Deals/Microsoft.md">Deal Note</MdLink>
 */

interface Props {
  path: string;         // Vault-relative path (e.g. "People/Name.md")
  title?: string;       // Display title (defaults to filename stem)
  children?: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

export function MdLink({ path, title, children, className, style }: Props) {
  const displayTitle = title || path.replace(/\.md$/, '').split('/').pop() || path;

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    window.dispatchEvent(new CustomEvent('views:open', {
      detail: {
        url: '/api/markdown/render?path=' + encodeURIComponent(path),
        title: displayTitle,
      },
    }));
  };

  return (
    <a
      href="#"
      onClick={handleClick}
      className={className}
      style={{ cursor: 'pointer', ...style }}
      title={`Open ${path} in Views`}
    >
      {children || displayTitle}
    </a>
  );
}

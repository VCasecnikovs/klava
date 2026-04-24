import type { ArtifactRef } from './types';

interface Props {
  artifact: ArtifactRef;
}

export function ArtifactCard({ artifact }: Props) {
  const isMarkdown = !!artifact.path;

  const handleClick = () => {
    if (isMarkdown) {
      // Open markdown file via render endpoint
      window.dispatchEvent(new CustomEvent('views:open', {
        detail: {
          url: '/api/markdown/render?path=' + encodeURIComponent(artifact.path!),
          title: artifact.title,
        },
      }));
    } else {
      // Open HTML view
      window.dispatchEvent(new CustomEvent('views:open', {
        detail: { filename: artifact.filename, title: artifact.title },
      }));
    }
  };

  return (
    <div className="artifact-card" onClick={handleClick}>
      <div className="artifact-card-icon">
        {isMarkdown ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="1" width="12" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <path d="M5 5.5L7 8.5 9 5.5M11 5.5v5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="1" width="12" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <path d="M5 5h6M5 8h6M5 11h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
        )}
      </div>
      <div className="artifact-card-content">
        <div className="artifact-card-title">{artifact.title}</div>
        <div className="artifact-card-filename">{artifact.path || artifact.filename}</div>
      </div>
      <div className="artifact-card-action">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    </div>
  );
}

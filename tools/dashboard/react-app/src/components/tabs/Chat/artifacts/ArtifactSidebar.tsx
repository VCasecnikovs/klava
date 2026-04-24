import { useChatContext } from '@/context/ChatContext';

export function ArtifactSidebar() {
  const { state, dispatch } = useChatContext();
  const { sessionArtifacts, activeArtifact } = state;

  // Hide when no artifacts or when actively viewing one (viewer takes the space)
  if (sessionArtifacts.length === 0 || activeArtifact) return null;

  return (
    <div className="artifact-sidebar">
      <div className="artifact-sidebar-header">Artifacts</div>
      <div className="artifact-sidebar-list">
        {sessionArtifacts.map((art, i) => (
          <div
            key={art.filename || art.path || i}
            className="artifact-sidebar-item"
            onClick={() => dispatch({ type: 'OPEN_ARTIFACT', filename: art.filename || art.path || '', title: art.title })}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="artifact-sidebar-icon">
              <rect x="2" y="1" width="12" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
              <path d="M5 5h6M5 8h6M5 11h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            <span className="artifact-sidebar-title" title={art.title}>{art.title}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

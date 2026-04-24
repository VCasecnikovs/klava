interface PanelProps {
  title?: string;
  help?: string;
  children: React.ReactNode;
}

export function Panel({ title, help, children }: PanelProps) {
  return (
    <div className="panel">
      {title && (
        <div className="panel-title">
          {title}
          {help && <span className="help-hint" data-help={help}>?</span>}
        </div>
      )}
      {children}
    </div>
  );
}

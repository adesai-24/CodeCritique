import React from 'react';
import { ScanLine, Moon, Sun, LayoutDashboard } from 'lucide-react';

const Sidebar = ({ 
  theme, 
  toggleTheme, 
  currentView, 
  onViewChange, 
  issues, 
  onIssueSelect,
  selectedIssueIndex,
  onRescan
}) => {
  
  // Group issues by file
  const startIdxMap = React.useMemo(() => {
     let map = {};
     // We need to map global index to local group index if needed, 
     // but here we just iterate and keep track of original index
     return map; 
  }, [issues]);

  const groups = React.useMemo(() => {
    const g = {};
    issues.forEach((issue, idx) => {
      if (!g[issue.file]) g[issue.file] = [];
      g[issue.file].push({ ...issue, originalIndex: idx });
    });
    return g;
  }, [issues]);

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="logo">
          <ScanLine /> CodeCritique
        </div>
        <button className="theme-toggle" onClick={toggleTheme} title="Toggle Theme">
          {theme === 'dark' ? <Moon size={20} /> : <Sun size={20} />}
        </button>
      </div>

      <div className="nav-menu">
        <div 
          className={`nav-item ${currentView === 'summary' ? 'active' : ''}`}
          onClick={() => onViewChange('summary')}
        >
          <LayoutDashboard size={18} /> Summary
        </div>
        <div className="nav-item" onClick={onRescan}>
          <ScanLine size={18} /> Rescan
        </div>
      </div>

      <div className="separator"></div>

      <div className="issue-list">
        {Object.keys(groups).map(file => (
          <div className="file-group" key={file}>
            <div className="file-header">
              <span>{file}</span> <span>{groups[file].length}</span>
            </div>
            {groups[file].map(item => (
              <div 
                key={item.originalIndex}
                className={`issue-card ${item.severity.toLowerCase()} ${selectedIssueIndex === item.originalIndex ? 'active' : ''}`}
                onClick={() => onIssueSelect(item.originalIndex)}
              >
                <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.25rem' }}>
                  {item.message}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.8rem', fontFamily: 'var(--font-mono)' }}>
                  Line {item.line}
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
};

export default Sidebar;

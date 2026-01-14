import React from 'react';
import { File, MapPin, Tag } from 'lucide-react';

const IssueDetail = ({ issue, onOpenFile }) => {
  if (!issue) return null;

  return (
    <div className="detail-view active">
      <div className="detail-header">
        <span className={`badge badge-${issue.severity.toLowerCase()}`} id="detailBadge">
          {issue.severity}
        </span>
        <h1 className="detail-title">{issue.message}</h1>
        
        <div style={{ display: 'flex', gap: '2rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.9rem' }}>
          <span 
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}
            onClick={() => onOpenFile(issue.file, issue.line)}
            title="Open in Editor"
          >
            <File size={14} />
            <span>{issue.file}</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <MapPin size={14} />
            <span>Line {issue.line}</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Tag size={14} />
            <span>{issue.code}</span>
          </span>
        </div>
      </div>

      <div style={{ marginBottom: '2rem' }}>
        <h4 style={{ textTransform: 'uppercase', letterSpacing: '0.1em', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>Reasoning</h4>
        <div style={{ background: 'var(--card-bg)', padding: '1.5rem', borderRadius: '12px', border: '1px solid var(--border-color)', lineHeight: 1.6 }}>
          {issue.reasoning || "No reasoning available."}
        </div>
      </div>

      <div>
        <h4 style={{ textTransform: 'uppercase', letterSpacing: '0.1em', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>Code Context</h4>
        <div className="code-block">
          {issue.code_context ? (
            issue.code_context.map((line, i) => {
              const lineNum = issue.context_start_line + i;
              const isError = lineNum === issue.line;
              return (
                <div className={`code-row ${isError ? 'error' : ''}`} key={i}>
                  <div className="code-num">{lineNum}</div>
                  <div className="code-content">{line}</div>
                </div>
              );
            })
          ) : (
            <div style={{ padding: '1rem', color: '#64748b' }}>No context available</div>
          )}
        </div>
      </div>
    </div>
  );
};

export default IssueDetail;

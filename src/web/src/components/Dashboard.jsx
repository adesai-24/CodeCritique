import React from 'react';
import { Sparkles } from 'lucide-react';

const Dashboard = ({ issues }) => {
  const fatalCount = issues.filter(i => i.severity === 'FATAL').length;
  const warningCount = issues.filter(i => i.severity === 'WARNING').length;
  const infoCount = issues.filter(i => i.severity === 'INFO').length;
  const totalIssues = issues.length;

  let grade = 'A';
  if (fatalCount > 0) grade = 'F';
  else if (totalIssues > 20) grade = 'C';
  else if (totalIssues > 10) grade = 'B';

  const gradeColor = grade === 'A' ? 'var(--severity-success)' : grade === 'F' ? 'var(--severity-fatal)' : 'var(--text-main)';

  return (
    <div id="viewSummary">
      <h1 style={{ marginBottom: '0.5rem', fontWeight: 800, fontSize: '2.5rem' }}>Analysis Summary</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: '3rem', fontSize: '1.1rem', maxWidth: '600px' }}>
        Here is the high-level breakdown of your codebase quality.
      </p>

      <div className="ai-banner">
        <div className="ai-content">
          <div style={{ background: 'rgba(139, 92, 246, 0.2)', padding: '12px', borderRadius: '12px', boxShadow: '0 0 20px rgba(139, 92, 246, 0.2)' }}>
            <Sparkles color="#C4B5FD" size={24} />
          </div>
          <div>
            <h3 style={{ marginBottom: '0.5rem', fontWeight: 700, fontSize: '1.1rem' }}>AI Insights</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '1rem', lineHeight: 1.6 }}>
              AI Insights are currently WIP.
            </p>
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        {/* Grade Card */}
        <div className="stat-card grade-card">
          <span className="stat-label">Overall Grade</span>
          <span className="stat-value" style={{ color: gradeColor }}>{grade}</span>
          <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginTop: 'auto', fontWeight: 500 }}>Based on issue density</span>
        </div>
        
        <div className="stat-card">
          <span className="stat-label" style={{ color: 'var(--severity-fatal)' }}>Fatal Issues</span>
          <span className="stat-value">{fatalCount}</span>
        </div>
        
        <div className="stat-card">
          <span className="stat-label" style={{ color: 'var(--severity-warning)' }}>Warnings</span>
          <span className="stat-value">{warningCount}</span>
        </div>
        
        <div className="stat-card">
          <span className="stat-label" style={{ color: 'var(--severity-info)' }}>Info / Nitpicks</span>
          <span className="stat-value">{infoCount}</span>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;

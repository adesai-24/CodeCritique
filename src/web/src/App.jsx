import React, { useState, useEffect } from 'react';
import './index.css';
import BackgroundBlobs from './components/BackgroundBlobs';
import Sidebar from './components/Sidebar';
import Dashboard from './components/Dashboard';
import IssueDetail from './components/IssueDetail';
import { mockIssues } from './data';

function App() {
  const [issues, setIssues] = useState([]);
  const [view, setView] = useState('summary'); // 'summary' or 'detail'
  const [selectedIssueIndex, setSelectedIssueIndex] = useState(null);
  const [theme, setTheme] = useState('dark');

  // Load initial data
  useEffect(() => {
    if (window.pywebview) {
        window.pywebview.api.get_issues().then(setIssues);
    } else {
        setIssues(mockIssues);
    }
  }, []);

  const handleRescan = async () => {
    if (window.pywebview) {
        const newIssues = await window.pywebview.api.rescan();
        setIssues(newIssues);
    } else {
        console.log("Rescanning (mock)...");
        setIssues([...mockIssues]);
    }
  };

  const handleOpenFile = (file, line) => {
    if (window.pywebview) {
        window.pywebview.api.open_file(file, line);
    } else {
        console.log(`Open ${file}:${line}`);
    }
  };

  // Theme Handling
  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);
    document.documentElement.setAttribute('data-theme', savedTheme);
  }, []);

  const toggleTheme = () => {
    const newTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
  };

  const handleIssueSelect = (index) => {
    setSelectedIssueIndex(index);
    setView('detail');
  };

  const handleViewChange = (newView) => {
    setView(newView);
    if (newView === 'summary') {
      setSelectedIssueIndex(null);
    }
  };

  return (
    <>
      <BackgroundBlobs />
      <Sidebar 
        theme={theme}
        toggleTheme={toggleTheme}
        currentView={view}
        onViewChange={handleViewChange}
        issues={issues}
        onIssueSelect={handleIssueSelect}
        selectedIssueIndex={selectedIssueIndex}
        onRescan={handleRescan}
      />
      
      <main className="main-content">
        {view === 'summary' && <Dashboard issues={issues} />}
        {view === 'detail' && selectedIssueIndex !== null && (
          <IssueDetail 
            issue={issues[selectedIssueIndex]} 
            onOpenFile={handleOpenFile}
          />
        )}
      </main>
    </>
  );
}

export default App;

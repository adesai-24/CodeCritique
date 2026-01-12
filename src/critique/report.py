import os
import webbrowser
import json
from typing import List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from critique.checkers.base import Issue, Severity

console = Console()

def print_report(issues: List[Issue]) -> bool:
    """
    Prints the issues to the console and generates an interactive HTML report.
    Returns True if passed (no FATAL), False if failed.
    """
    # 1. Console Output (Keep it for immediate feedback)
    if not issues:
        console.print(Panel("[bold green]All Clean! Code looks great.[/bold green]", title="Critique Result"))
        generate_html_report(issues) # Still generate a "success" report
        return True

    fatal_issues = [i for i in issues if i.severity == Severity.FATAL]
    warnings = [i for i in issues if i.severity == Severity.WARNING]
    infos = [i for i in issues if i.severity == Severity.INFO]

    table = Table(title="Code Critique Report", show_lines=True)
    table.add_column("Severity", style="bold")
    table.add_column("Location")
    table.add_column("Message")
    table.add_column("Reasoning", style="dim")

    for issue in fatal_issues + warnings + infos:
        sev_style = "red" if issue.severity == Severity.FATAL else "yellow" if issue.severity == Severity.WARNING else "blue"
        
        try:
            display_path = os.path.relpath(issue.file_path)
        except Exception:
            display_path = issue.file_path

        loc = f"{display_path}:{issue.line}"
        if issue.column:
            loc += f":{issue.column}"
            
        table.add_row(
            f"[{sev_style}]{issue.severity.value}[/{sev_style}]",
            loc,
            f"{issue.message} ({issue.code})",
            issue.reasoning or ""
        )

    console.print(table)

    report_path = generate_html_report(issues)
    console.print(f"\n[bold blue]Interactive report generated at: {report_path}[/bold blue]")
    
    try:
        webbrowser.open(f"file://{os.path.abspath(report_path)}")
    except Exception:
        pass

    if fatal_issues:
        console.print(f"\n[bold red]\U0001F6AB Fix {len(fatal_issues)} FATAL issues to push.[/bold red]")
        return False
    elif warnings:
        console.print(f"\n[bold yellow]\U000026A0 Found {len(warnings)} WARNINGS.[/bold yellow]")
        return True
    
    return True

def generate_html_report(issues: List[Issue]) -> str:
    """
    Generates a premium interactive HTML report.
    Returns the path to the generated file.
    """
    report_file = "critique_report.html"
    
    issues_data = []
    for i in issues:
        try:
            rel_file = os.path.relpath(i.file_path)
        except Exception:
            rel_file = i.file_path
            
        issues_data.append({
            "severity": i.severity.value,
            "file": rel_file,
            "line": i.line,
            "column": i.column,
            "message": i.message,
            "code": i.code,
            "reasoning": i.reasoning,
            "code_context": i.code_context,
            "context_start_line": max(1, i.line - 3)
        })

    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CodeCritique Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0d0e14;
            --sidebar-bg: rgba(255, 255, 255, 0.03);
            --card-bg: rgba(255, 255, 255, 0.05);
            --text-color: #e0e0e0;
            --text-dim: #a0a0a0;
            --accent-purple: #8b5cf6;
            --accent-blue: #3b82f6;
            --fatal-red: #ef4444;
            --warning-yellow: #f59e0b;
            --info-blue: #3b82f6;
            --success-green: #10b981;
            --glass-border: rgba(255, 255, 255, 0.1);
            --font-main: 'Inter', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: var(--font-main);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }}

        /* Sidebar */
        .sidebar {{
            width: 350px;
            background: var(--sidebar-bg);
            border-right: 1px solid var(--glass-border);
            display: flex;
            flex-direction: column;
            backdrop-filter: blur(10px);
        }}

        .sidebar-header {{
            padding: 2rem;
            border-bottom: 1px solid var(--glass-border);
        }}

        .sidebar-header h1 {{
            font-size: 1.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-purple), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .issue-list {{
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
        }}

        .issue-item {{
            padding: 1rem;
            margin-bottom: 0.75rem;
            background: var(--card-bg);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
            overflow: hidden;
        }}

        .issue-item:hover {{
            background: rgba(255, 255, 255, 0.08);
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.2);
        }}

        .issue-item.active {{
            background: rgba(139, 92, 246, 0.15);
            border-color: var(--accent-purple);
        }}

        .issue-item .severity-indicator {{
            width: 4px;
            height: 100%;
            position: absolute;
            left: 0;
            top: 0;
        }}

        .sev-fatal {{ background-color: var(--fatal-red); }}
        .sev-warning {{ background-color: var(--warning-yellow); }}
        .sev-info {{ background-color: var(--info-blue); }}

        .issue-item h3 {{
            font-size: 0.9rem;
            margin-bottom: 0.25rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .issue-item p {{
            font-size: 0.75rem;
            color: var(--text-dim);
            font-family: var(--font-mono);
        }}

        /* Main Content */
        .main-content {{
            flex: 1;
            display: flex;
            flex-direction: column;
            background: radial-gradient(circle at top right, rgba(139, 92, 246, 0.05), transparent);
            padding: 3rem;
            overflow-y: auto;
        }}

        .empty-state {{
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            text-align: center;
        }}

        .empty-state h2 {{
            font-size: 2rem;
            margin-bottom: 1rem;
            color: var(--success-green);
        }}

        .issue-detail {{
            display: none;
            max-width: 900px;
            margin: 0 auto;
            width: 100%;
        }}

        .issue-detail.active {{
            display: block;
            animation: fadeIn 0.3s ease;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .detail-header {{
            margin-bottom: 2rem;
        }}

        .detail-header .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            margin-bottom: 1rem;
        }}

        .badge-fatal {{ background: rgba(239, 68, 68, 0.2); color: var(--fatal-red); border: 1px solid var(--fatal-red); }}
        .badge-warning {{ background: rgba(245, 158, 11, 0.2); color: var(--warning-yellow); border: 1px solid var(--warning-yellow); }}
        .badge-info {{ background: rgba(59, 130, 246, 0.2); color: var(--info-blue); border: 1px solid var(--info-blue); }}

        .detail-header h2 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}

        .detail-meta {{
            display: flex;
            gap: 1.5rem;
            color: var(--text-dim);
            font-family: var(--font-mono);
            font-size: 0.9rem;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--glass-border);
        }}

        .detail-section {{
            margin-bottom: 2.5rem;
        }}

        .detail-section h4 {{
            font-size: 0.8rem;
            text-transform: uppercase;
            color: var(--text-dim);
            letter-spacing: 0.1em;
            margin-bottom: 1rem;
        }}

        .reasoning-box {{
            background: var(--card-bg);
            border: 1px solid var(--glass-border);
            padding: 1.5rem;
            border-radius: 12px;
            line-height: 1.6;
        }}

        .code-snippet {{
            background: #1a1b26;
            padding: 1.5rem;
            border-radius: 12px;
            font-family: var(--font-mono);
            font-size: 0.85rem;
            overflow-x: auto;
            border: 1px solid var(--glass-border);
            line-height: 1.5;
        }}

        .code-snippet pre {{
             margin: 0;
        }}

        .code-line {{
            display: flex;
            gap: 1.5rem;
        }}

        .line-num {{
            color: var(--text-dim);
            text-align: right;
            min-width: 2.5rem;
            user-select: none;
            opacity: 0.5;
        }}

        .line-content {{
            white-space: pre;
        }}

        .line-error {{
            background: rgba(239, 68, 68, 0.15);
            margin: 0 -1.5rem;
            padding: 0 1.5rem;
            border-left: 3px solid var(--fatal-red);
        }}

        /* Custom scrollbar */
        ::-webkit-scrollbar {{
            width: 8px;
        }}
        ::-webkit-scrollbar-track {{
            background: transparent;
        }}
        ::-webkit-scrollbar-thumb {{
            background: var(--glass-border);
            border-radius: 10px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: rgba(255, 255, 255, 0.2);
        }}
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h1>CodeCritique</h1>
        </div>
        <div class="issue-list" id="issueList">
            <!-- Issues injected here -->
        </div>
    </div>
    <main class="main-content" id="mainContent">
        <div class="empty-state" id="emptyState">
            <h2>{ "No Issues Found!" if not issues else "Select an issue to see details" }</h2>
            <p>{ "Your code is shining bright." if not issues else "Choose from the list on the left." }</p>
        </div>
        
        <div class="issue-detail" id="issueDetail">
            <div class="detail-header">
                <span id="detailBadge" class="badge">FATAL</span>
                <h2 id="detailTitle">Title</h2>
            </div>
            <div class="detail-meta">
                <span id="detailFile">file.py</span>
                <span id="detailLoc">Line 10, Col 5</span>
                <span id="detailCode">CODE001</span>
            </div>
            
            <div class="detail-section">
                <h4>Reasoning & Recommendation</h4>
                <div class="reasoning-box" id="detailReasoning">
                    Detailed explanation goes here.
                </div>
            </div>

            <div class="detail-section">
                <h4>Context</h4>
                <div class="code-snippet" id="detailCodeSnippet">
                    <!-- Context injected here -->
                </div>
            </div>
        </div>
    </main>

    <script>
        const issues = {json.dumps(issues_data)};
        const issueList = document.getElementById('issueList');
        const issueDetail = document.getElementById('issueDetail');
        const emptyState = document.getElementById('emptyState');

        function renderIssues() {{
            if (issues.length === 0) return;

            issues.forEach((issue, index) => {{
                const item = document.createElement('div');
                item.className = 'issue-item';
                item.innerHTML = `
                    <div class="severity-indicator sev-${{issue.severity.toLowerCase()}}"></div>
                    <h3>${{issue.message}}</h3>
                    <p>${{issue.file.split(/[\\\\/]/).pop()}}:${{issue.line}}</p>
                `;
                item.onclick = () => showIssue(index, item);
                issueList.appendChild(item);
            }});
        }}

        function showIssue(index, element) {{
            const issue = issues[index];
            
            // UI Updates
            document.querySelectorAll('.issue-item').forEach(i => i.classList.remove('active'));
            element.classList.add('active');
            
            emptyState.style.display = 'none';
            issueDetail.classList.add('active');

            document.getElementById('detailBadge').className = `badge badge-${{issue.severity.toLowerCase()}}`;
            document.getElementById('detailBadge').innerText = issue.severity;
            document.getElementById('detailTitle').innerText = issue.message;
            document.getElementById('detailFile').innerText = issue.file;
            document.getElementById('detailLoc').innerText = `Line ${{issue.line}}${{issue.column ? ', Col ' + issue.column : ''}}`;
            document.getElementById('detailCode').innerText = issue.code;
            document.getElementById('detailReasoning').innerText = issue.reasoning || 'No specific reasoning provided.';

            // Render Context
            const contextContainer = document.getElementById('detailCodeSnippet');
            contextContainer.innerHTML = '';
            
            if (issue.code_context && issue.code_context.length > 0) {{
                issue.code_context.forEach((line, i) => {{
                    const lineNum = issue.context_start_line + i;
                    const isErrorLine = lineNum === issue.line;
                    
                    const lineDiv = document.createElement('div');
                    lineDiv.className = `code-line ${{isErrorLine ? 'line-error' : ''}}`;
                    lineDiv.innerHTML = `
                        <span class="line-num">${{lineNum}}</span>
                        <span class="line-content">${{escapeHtml(line)}}</span>
                    `;
                    contextContainer.appendChild(lineDiv);
                }});
            }} else {{
                contextContainer.innerHTML = '<p style="color: var(--text-dim); font-style: italic;">No code context available.</p>';
            }}
        }}

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        renderIssues();
    </script>
</body>
</html>
    """
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(html_template)
        
    return report_file

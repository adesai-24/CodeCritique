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

    # 2. Generate Interactive HTML Report
    # Note: Temporarily disabled for transition to application-based UI
    # report_path = generate_html_report(issues)
    # console.print(f"\n[bold blue]Interactive report generated at: {report_path}[/bold blue]")
    
    # Optionally open it automatically
    # try:
    #     webbrowser.open(f"file://{os.path.abspath(report_path)}")
    # except Exception:
    #     pass

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

    # Stats for Dashboard
    stats = {
        "total": len(issues),
        "fatal": len([i for i in issues if i.severity == Severity.FATAL]),
        "warning": len([i for i in issues if i.severity == Severity.WARNING]),
        "info": len([i for i in issues if i.severity == Severity.INFO]),
    }

    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CodeCritique Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/lucide@latest"></script>
    <style>
        :root {{
            /* Dark Theme (Default) */
            --bg-color: #0F0F13;
            --sidebar-bg: rgba(20, 20, 25, 0.6);
            --card-bg: rgba(255, 255, 255, 0.03);
            --card-hover: rgba(255, 255, 255, 0.06);
            --text-main: #FFFFFF;
            --text-muted: #A1A1AA;
            --border-color: rgba(255, 255, 255, 0.08);
            
            --accent-primary: #8B5CF6; /* Violet */
            --accent-secondary: #3B82F6; /* Blue */
            --accent-glow: rgba(139, 92, 246, 0.3);

            --severity-fatal: #FF4D4D;
            --severity-warning: #FFB84C;
            --severity-info: #3B82F6;
            --severity-success: #10B981;

            --font-main: 'Outfit', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
            
            --blob-1: #4C1D95;
            --blob-2: #1E3A8A;
            --blob-3: #831843;
        }}

        [data-theme="light"] {{
            --bg-color: #F8FAFC;
            --sidebar-bg: rgba(255, 255, 255, 0.7);
            --card-bg: rgba(255, 255, 255, 0.6);
            --card-hover: rgba(255, 255, 255, 0.8);
            --text-main: #1E293B;
            --text-muted: #64748B;
            --border-color: rgba(0, 0, 0, 0.06);

            --accent-primary: #7C3AED;
            --accent-secondary: #2563EB;
            --accent-glow: rgba(124, 58, 237, 0.15);
            
            --severity-fatal: #DC2626;
            --severity-warning: #D97706;
            --severity-info: #2563EB;
            --severity-success: #059669;

            --blob-1: #E0E7FF;
            --blob-2: #DBEAFE;
            --blob-3: #FCE7F3;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            transition: background-color 0.3s ease, border-color 0.3s ease, color 0.3s ease;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: var(--font-main);
            height: 100vh;
            overflow: hidden;
            display: flex;
            position: relative;
        }}

         /* Liquid Background */
        .background-blobs {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -1;
            overflow: hidden;
            filter: blur(80px);
            opacity: 1; /* More vibrant */
        }}

        .blob {{
            position: absolute;
            border-radius: 50%;
            animation: float 20s infinite ease-in-out;
            mix-blend-mode: normal; /* Better for deep colors */
        }}

        .blob-1 {{ width: 700px; height: 700px; background: radial-gradient(circle, var(--blob-1) 0%, transparent 70%); top: -100px; left: -100px; animation-delay: 0s; }}
        .blob-2 {{ width: 600px; height: 600px; background: radial-gradient(circle, var(--blob-2) 0%, transparent 70%); bottom: -100px; right: -100px; animation-delay: -5s; }}
        .blob-3 {{ width: 500px; height: 500px; background: radial-gradient(circle, var(--blob-3) 0%, transparent 70%); top: 40%; left: 40%; animation-delay: -10s; }}

        @keyframes float {{
            0% {{ transform: translate(0, 0) scale(1); }}
            33% {{ transform: translate(30px, -50px) scale(1.1); }}
            66% {{ transform: translate(-20px, 20px) scale(0.9); }}
            100% {{ transform: translate(0, 0) scale(1); }}
        }}

        /* Sidebar - Volumetric Glass */
        .sidebar {{
            width: 380px;
            background: rgba(30, 30, 35, 0.4);
            backdrop-filter: blur(50px) saturate(200%);
            -webkit-backdrop-filter: blur(50px) saturate(200%);
            border-right: 1px solid rgba(255, 255, 255, 0.1);
            display: flex;
            flex-direction: column;
            z-index: 10;
            box-shadow: 
                20px 0 40px rgba(0,0,0,0.2),
                inset -1px 0 0 rgba(255, 255, 255, 0.05); /* Inner edge light */
        }}

        [data-theme="light"] .sidebar {{
            background: rgba(255, 255, 255, 0.6);
            border-right: 1px solid rgba(255, 255, 255, 0.4);
        }}

        .sidebar-header {{
            padding: 2rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .logo {{
            font-size: 1.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, #fff, #aaa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            text-shadow: 0 2px 10px rgba(255,255,255,0.1);
        }}

        [data-theme="light"] .logo {{
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: none;
        }}

        .theme-toggle {{
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--text-main);
            cursor: pointer;
            padding: 0.6rem;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
        }}

        .theme-toggle:hover {{
            background: rgba(255, 255, 255, 0.2);
            transform: scale(1.1);
            box-shadow: 0 8px 16px rgba(0,0,0,0.2);
        }}

        .nav-menu {{
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }}

        .nav-item {{
            padding: 1rem 1.25rem;
            border-radius: 99px; /* Pill Shape */
            cursor: pointer;
            color: var(--text-muted);
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 1rem;
            transition: all 0.3s;
            border: 1px solid transparent;
        }}

        .nav-item:hover {{
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-main);
            box-shadow: inset 0 0 20px rgba(255,255,255,0.02);
        }}

        .nav-item.active {{
            background: rgba(139, 92, 246, 0.15);
            color: #fff;
            border: 1px solid rgba(139, 92, 246, 0.3);
            box-shadow: 
                0 4px 20px rgba(139, 92, 246, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.2);
        }}

        .separator {{
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
            margin: 0.5rem 2rem;
        }}

        .issue-list {{
            flex: 1;
            overflow-y: auto;
            padding: 0 1.5rem 1.5rem 1.5rem;
        }}

        .file-group {{
            margin-bottom: 2rem;
        }}

        .file-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.75rem 0.5rem;
            color: var(--text-muted);
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            cursor: pointer;
            user-select: none;
            opacity: 0.8;
        }}

        .file-header:hover {{ color: var(--text-main); opacity: 1; }}

        /* Volumetric Issue Card */
        .issue-card {{
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(20px) saturate(180%);
            -webkit-backdrop-filter: blur(20px) saturate(180%);
            border-radius: 24px; /* Big rounding */
            padding: 1.5rem;
            margin-bottom: 1rem;
            cursor: pointer;
            position: relative;
            transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1); /* Bouncy spring */
            
            /* VisionOS Volumetric Shadow */
            box-shadow: 
                0 4px 20px rgba(0, 0, 0, 0.1),
                inset 0 1px 0 rgba(255, 255, 255, 0.1), /* Top Rim */
                inset 0 0 20px rgba(255, 255, 255, 0.02); /* Inner Volume */
                
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}

        .issue-card:hover {{
            transform: scale(1.02) translateY(-2px);
            background: rgba(255, 255, 255, 0.07);
            box-shadow: 
                0 20px 40px rgba(0, 0, 0, 0.2),
                inset 0 1px 0 rgba(255, 255, 255, 0.3), /* Brighter Rim */
                inset 0 0 30px rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.2);
            z-index: 5;
        }}
        
        .issue-card::before {{
            content: '';
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            height: 60%;
            width: 4px;
            border-radius: 4px;
            background: var(--text-muted);
            opacity: 0.3;
            transition: all 0.3s;
        }}
        
        .issue-card.fatal::before {{ background: var(--severity-fatal); opacity: 1; box-shadow: 0 0 10px var(--severity-fatal); }}
        .issue-card.warning::before {{ background: var(--severity-warning); opacity: 1; box-shadow: 0 0 10px var(--severity-warning); }}
        .issue-card.info::before {{ background: var(--severity-info); opacity: 1; box-shadow: 0 0 10px var(--severity-info); }}

        .issue-card.active {{
            background: rgba(139, 92, 246, 0.15); /* Tinted Volume */
            box-shadow: 
                0 10px 30px rgba(139, 92, 246, 0.2),
                inset 0 0 0 1px rgba(139, 92, 246, 0.4),
                inset 0 1px 0 rgba(255, 255, 255, 0.2);
        }}

        /* Main Content */
        .main-content {{
            flex: 1;
            position: relative;
            z-index: 1;
            overflow-y: auto;
            padding: 4rem 5rem;
        }}

        /* Dashboard View */
        .dashboard-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 2.5rem;
            margin-bottom: 4rem;
        }}

        .stat-card {{
            height: 100%;
            background: rgba(255, 255, 255, 0.02);
            backdrop-filter: blur(40px) saturate(200%);
            -webkit-backdrop-filter: blur(40px) saturate(200%);
            border-radius: 32px; /* Super Round */
            padding: 2.5rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
            position: relative;
            transition: all 0.4s ease;
            
            /* Deep Glass Volume */
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 
                0 20px 50px rgba(0,0,0,0.15),
                inset 0 1px 0 rgba(255,255,255,0.1),
                inset 0 0 40px rgba(255,255,255,0.02);
        }}

        .stat-card:hover {{
            transform: translateY(-5px);
            background: rgba(255, 255, 255, 0.05);
            box-shadow: 
                0 30px 60px rgba(0,0,0,0.25),
                inset 0 1px 0 rgba(255,255,255,0.2),
                inset 0 0 20px rgba(255,255,255,0.05);
            border-color: rgba(255, 255, 255, 0.2);
        }}

        .stat-card.grade-card {{
            /* Iridescent / Chromatic Feel */
            background: linear-gradient(135deg, rgba(139, 92, 246, 0.1), rgba(59, 130, 246, 0.1));
            border: 1px solid rgba(139, 92, 246, 0.2);
            box-shadow: 
                0 20px 50px rgba(139, 92, 246, 0.15),
                inset 0 1px 0 rgba(255,255,255, 0.2);
        }}

        .stat-label {{
            font-size: 0.9rem;
            color: var(--text-muted);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            opacity: 0.8;
        }}

        .stat-value {{
            font-size: 4rem;
            font-weight: 800;
            background: linear-gradient(180deg, #fff, #bbb);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.03em;
            line-height: 1;
            filter: drop-shadow(0 2px 10px rgba(255,255,255,0.1));
        }}

        [data-theme="light"] .stat-value {{
            background: linear-gradient(180deg, var(--text-main), var(--text-muted));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            filter: none;
        }}

        .ai-banner {{
            /* Holographic Border Effect */
            background: linear-gradient(90deg, 
                var(--accent-primary), 
                #EC4899, 
                var(--accent-secondary), 
                var(--accent-primary)
            );
            background-size: 200% 100%;
            animation: shimmer 10s linear infinite;
            border-radius: 34px;
            padding: 2px;
            margin-bottom: 3rem;
            box-shadow: 0 20px 40px rgba(139, 92, 246, 0.15);
        }}

        @keyframes shimmer {{
            0% {{ background-position: 0% 50%; }}
            100% {{ background-position: 200% 50%; }}
        }}

        .ai-content {{
            background: rgba(10, 10, 15, 0.6);
            backdrop-filter: blur(30px);
            border-radius: 32px;
            padding: 3rem;
            display: flex;
            align-items: center;
            gap: 2.5rem;
            box-shadow: inset 0 0 40px rgba(0,0,0,0.2);
        }}

        [data-theme="light"] .ai-content {{
            background: rgba(255, 255, 255, 0.85);
            box-shadow: inset 0 0 20px rgba(255,255,255,0.5);
        }}

        /* Issue Detail View */
        .detail-view {{
            display: none;
            max-width: 900px;
            margin: 0 auto;
            animation: fadeIn 0.4s ease;
        }}
        
        .detail-view.active {{ display: block; }}

        .detail-header {{
            margin-bottom: 2rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
        }}

        .badge {{
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.75rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 1rem;
        }}

        .badge-fatal {{ background: rgba(255, 77, 77, 0.15); color: var(--severity-fatal); }}
        .badge-warning {{ background: rgba(255, 184, 76, 0.15); color: var(--severity-warning); }}
        .badge-info {{ background: rgba(59, 130, 246, 0.15); color: var(--severity-info); }}

        .detail-title {{
            font-size: 2rem;
            line-height: 1.2;
            margin-bottom: 1rem;
        }}

        .code-block {{
            background: #1e1e1e; /* Always dark for code */
            border-radius: 12px;
            border: 1px solid var(--border-color);
            overflow: hidden;
            font-family: var(--font-mono);
            font-size: 0.9rem;
            margin-top: 1rem;
        }}

        .code-row {{
            display: flex;
            line-height: 1.6;
        }}

        .code-num {{
            width: 3rem;
            text-align: right;
            padding-right: 1rem;
            color: #64748b;
            background: rgba(255, 255, 255, 0.03);
            user-select: none;
        }}

        .code-content {{
            flex: 1;
            padding-left: 1rem;
            color: #e2e8f0;
            white-space: pre;
        }}

        .code-row.error {{
            background: rgba(220, 38, 38, 0.15);
        }}
        
        .code-row.error .code-num {{
             border-right: 2px solid var(--severity-fatal);
             color: var(--severity-fatal);
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .hidden {{ display: none !important; }}
    </style>
</head>
<body>
    <div class="background-blobs">
        <div class="blob blob-1"></div>
        <div class="blob blob-2"></div>
        <div class="blob blob-3"></div>
    </div>

    <aside class="sidebar">
        <div class="sidebar-header">
            <div class="logo">
                <i data-lucide="scan-line"></i> CodeCritique
            </div>
            <button class="theme-toggle" id="themeBtn" title="Toggle Theme">
                <i data-lucide="moon"></i>
            </button>
        </div>

        <div class="nav-menu">
            <div class="nav-item active" id="navSummary">
                <i data-lucide="layout-dashboard" size="18"></i> Summary
            </div>
        </div>

        <div class="separator"></div>

        <div class="issue-list" id="issueList">
            <!-- JS Injected -->
        </div>
    </aside>

    <main class="main-content">
        <!-- Dashboard View -->
        <div id="viewSummary">
            <h1 style="margin-bottom: 0.5rem; font-weight: 800; font-size: 2.5rem;">Analysis Summary</h1>
            <p style="color: var(--text-muted); margin-bottom: 3rem; font-size: 1.1rem; max-width: 600px;">Here is the high-level breakdown of your codebase quality.</p>

            <div class="ai-banner">
                <div class="ai-content">
                    <div style="background: rgba(139, 92, 246, 0.2); padding: 12px; border-radius: 12px; box-shadow: 0 0 20px rgba(139, 92, 246, 0.2);">
                        <i data-lucide="sparkles" color="#C4B5FD" size="24"></i>
                    </div>
                    <div>
                        <!-- WIP -->
                        <h3 style="margin-bottom: 0.5rem; font-weight: 700; font-size: 1.1rem;">AI Insights</h3>
                        <p style="color: var(--text-muted); font-size: 1rem; line-height: 1.6;">
                            AI Insights are currently WIP.
                        </p>
                    </div>
                </div>
            </div>

            <div class="dashboard-grid">
                <!-- Grade Card -->
                <div class="stat-card grade-card">
                    <span class="stat-label">Overall Grade</span>
                    <span class="stat-value" id="gradeValue">A</span>
                    <span style="font-size: 0.9rem; color: var(--text-muted); margin-top: auto; font-weight: 500;">Based on issue density</span>
                </div>
                
                <div class="stat-card">
                    <span class="stat-label" style="color: var(--severity-fatal)">Fatal Issues</span>
                    <span class="stat-value">{stats['fatal']}</span>
                </div>
                
                <div class="stat-card">
                    <span class="stat-label" style="color: var(--severity-warning)">Warnings</span>
                    <span class="stat-value">{stats['warning']}</span>
                </div>
                
                <div class="stat-card">
                    <span class="stat-label" style="color: var(--severity-info)">Info / Nitpicks</span>
                    <span class="stat-value">{stats['info']}</span>
                </div>
            </div>
        </div>

        <!-- Issue Detail View -->
        <div id="viewDetail" class="detail-view">
            <div class="detail-header">
                <span id="detailBadge" class="badge">FATAL</span>
                <h1 id="detailMessage" class="detail-title">Function name should be snake_case</h1>
                
                <div style="display: flex; gap: 2rem; color: var(--text-muted); font-family: var(--font-mono); font-size: 0.9rem;">
                    <span style="display: flex; align-items: center; gap: 0.5rem;">
                        <i data-lucide="file" size="14"></i>
                        <span id="detailFile">utils.py</span>
                    </span>
                    <span style="display: flex; align-items: center; gap: 0.5rem;">
                        <i data-lucide="map-pin" size="14"></i>
                        <span id="detailLine">Line 42</span>
                    </span>
                    <span style="display: flex; align-items: center; gap: 0.5rem;">
                        <i data-lucide="tag" size="14"></i>
                        <span id="detailCode">N802</span>
                    </span>
                </div>
            </div>

            <div style="margin-bottom: 2rem;">
                <h4 style="text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 1rem;">Reasoning</h4>
                <div id="detailReasoning" style="background: var(--card-bg); padding: 1.5rem; border-radius: 12px; border: 1px solid var(--border-color); line-height: 1.6;">
                    Loading...
                </div>
            </div>

            <div>
                <h4 style="text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 1rem;">Code Context</h4>
                <div id="detailContext" class="code-block">
                    <!-- Context injected here -->
                </div>
            </div>
        </div>
    </main>

    <script>
        // Data Configuration
        const issues = {json.dumps(issues_data)};
        const totalIssues = {stats['total']};
        const fatalCount = {stats['fatal']};
        
        // Calculate Grade
        const gradeEl = document.getElementById('gradeValue');
        let grade = 'A';
        if (fatalCount > 0) grade = 'F';
        else if (totalIssues > 20) grade = 'C';
        else if (totalIssues > 10) grade = 'B';
        gradeEl.textContent = grade;
        gradeEl.style.color = grade === 'A' ? 'var(--severity-success)' : grade === 'F' ? 'var(--severity-fatal)' : 'var(--text-main)';

        // Icons
        lucide.createIcons();

        // Theme Logic
        const themeBtn = document.getElementById('themeBtn');
        
        function setTheme(theme) {{
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            themeBtn.innerHTML = `<i data-lucide="${{theme === 'dark' ? 'moon' : 'sun'}}"></i>`;
            lucide.createIcons();
        }}

        // Init Theme
        const savedTheme = localStorage.getItem('theme') || 'dark';
        setTheme(savedTheme);

        themeBtn.addEventListener('click', () => {{
            const current = document.documentElement.getAttribute('data-theme') || 'dark';
            setTheme(current === 'dark' ? 'light' : 'dark');
        }});

        // View Switching
        const navSummary = document.getElementById('navSummary');
        const viewSummary = document.getElementById('viewSummary');
        const viewDetail = document.getElementById('viewDetail');
        const issueList = document.getElementById('issueList');

        function showSummary() {{
            viewSummary.classList.remove('hidden');
            viewDetail.classList.remove('active');
            navSummary.classList.add('active');
            document.querySelectorAll('.issue-card').forEach(el => el.classList.remove('active'));
        }}

        navSummary.addEventListener('click', showSummary);

        function showIssue(index, cardEl) {{
            const issue = issues[index];
            
            // Switch View
            viewSummary.classList.add('hidden');
            viewDetail.classList.add('active');
            navSummary.classList.remove('active');
            
            // Highlight Side Nav
            document.querySelectorAll('.issue-card').forEach(el => el.classList.remove('active'));
            cardEl.classList.add('active');

            // Populate Data
            document.getElementById('detailMessage').textContent = issue.message;
            document.getElementById('detailFile').textContent = issue.file;
            document.getElementById('detailLine').textContent = `Line ${{issue.line}}`;
            document.getElementById('detailCode').textContent = issue.code;
            document.getElementById('detailReasoning').textContent = issue.reasoning || "No reasoning available.";
            
            const badge = document.getElementById('detailBadge');
            badge.className = `badge badge-${{issue.severity.toLowerCase()}}`;
            badge.textContent = issue.severity;

            // Render Context
            const ctxContainer = document.getElementById('detailContext');
            ctxContainer.innerHTML = '';
            
            if (issue.code_context) {{
                issue.code_context.forEach((line, i) => {{
                    const lineNum = issue.context_start_line + i;
                    const isError = lineNum === issue.line;
                    
                    const row = document.createElement('div');
                    row.className = `code-row ${{isError ? 'error' : ''}}`;
                    row.innerHTML = `
                        <div class="code-num">${{lineNum}}</div>
                        <div class="code-content">${{escapeHtml(line)}}</div>
                    `;
                    ctxContainer.appendChild(row);
                }});
            }} else {{
                ctxContainer.innerHTML = '<div style="padding:1rem; color: #64748b;">No context available</div>';
            }}
        }}

        function escapeHtml(text) {{
             if (!text) return '';
             return text
                 .replace(/&/g, "&amp;")
                 .replace(/</g, "&lt;")
                 .replace(/>/g, "&gt;")
                 .replace(/"/g, "&quot;")
                 .replace(/'/g, "&#039;");
        }}

        // Render Sidebar Issues
        const groups = {{}};
        issues.forEach((issue, idx) => {{
            if (!groups[issue.file]) groups[issue.file] = [];
            groups[issue.file].push({{...issue, idx}});
        }});

        Object.keys(groups).forEach(file => {{
            const groupWrap = document.createElement('div');
            groupWrap.className = 'file-group';
            
            const header = document.createElement('div');
            header.className = 'file-header';
            header.innerHTML = `<span>${{file}}</span> <span>${{groups[file].length}}</span>`;
            
            groupWrap.appendChild(header);

            groups[file].forEach(item => {{
                const card = document.createElement('div');
                card.className = `issue-card ${{item.severity.toLowerCase()}}`;
                card.innerHTML = `
                    <div style="font-weight:600; font-size:0.9rem; margin-bottom:0.25rem;">${{item.message}}</div>
                    <div style="color:var(--text-muted); font-size:0.8rem; font-family:var(--font-mono);">Line ${{item.line}}</div>
                `;
                card.addEventListener('click', () => showIssue(item.idx, card));
                groupWrap.appendChild(card);
            }});

            issueList.appendChild(groupWrap);
        }});

    </script>
</body>
</html>
    """
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(html_template)
        
    return report_file

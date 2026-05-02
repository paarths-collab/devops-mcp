import os
import re
import glob

base = r'C:\Users\PaarthGala\Coding\devops-mcp\docs'
files = glob.glob(os.path.join(base, '*.md'))

replacements = [
    (r'\bmemory/', 'devops_agent/memory/'),
    (r'\btools/', 'devops_agent/tools/'),
    (r'\bcli\.py\b', 'devops_agent/cli.py'),
    (r'\bmain\.py\b', 'devops_agent/main.py'),
    (r'\bserver\.py\b', 'observable_agent_panel/server.py'),
    (r'\bcore/analyzer\.py\b', 'observable_agent_panel/core/analyzer.py'),
    (r'\bcore/trace_db\.py\b', 'observable_agent_panel/core/trace_db.py'),
    (r'\bcore/observability\.py\b', 'observable_agent_panel/core/observability.py'),
    (r'\bcore/orchestrator\.py\b', 'devops_agent/core/orchestrator.py'),
    (r'\bcore/llm_client\.py\b', 'devops_agent/core/llm_client.py'),
    (r'\bcore/(__init__\.py)?\b', 'devops_agent/core/'),
]

for fpath in files:
    if os.path.basename(fpath) in ['README.md', 'REORGANIZATION.md', 'agent_prompt.md']:
        continue
        
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    new = content
    for pattern, repl in replacements:
        new = re.sub(pattern, repl, new)
        
    if new != content:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(new)
        print(f"Updated {os.path.basename(fpath)}")
        
print("Done patching old docs.")

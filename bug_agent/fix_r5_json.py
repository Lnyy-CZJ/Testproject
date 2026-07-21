import re, os

BASE = "/Users/jame/Workspace/bug_agent/server/internal"

target_files = [
    "service/fix_engine.go",
    "service/analysis.go",
    "service/collaboration.go",
    "handler/fix_task.go",
]

total = 0
for fname in target_files:
    fp = os.path.join(BASE, fname)
    with open(fp, 'r') as f:
        content = f.read()
    
    original = content
    
    # Replace: json.Unmarshal(xxx, &yyy) with error check
    # Pattern: json.Unmarshal([]byte(xxx), &yyy) - standalone line (no if/err)
    lines = content.split('\n')
    new_lines = []
    
    for line in lines:
        stripped = line.strip()
        indent = line[:len(line) - len(line.lstrip())]
        
        # Skip lines that already check error
        if 'err' in line and 'json.Unmarshal' in line:
            new_lines.append(line)
            continue
        
        # Match standalone json.Unmarshal calls
        match = re.match(r'^([\w.]+)\s*=\s*json\.Unmarshal\((.+),\s*(.+)\)\s*$', stripped)
        if match:
            # Already has assignment, just missing error check
            new_lines.append(line)
            continue
        
        match2 = re.match(r'^json\.Unmarshal\((.+),\s*(.+)\)\s*$', stripped)
        if match2:
            arg1 = match2.group(1)
            arg2 = match2.group(2)
            new_lines.append(f'{indent}if err := json.Unmarshal({arg1}, {arg2}); err != nil {{')
            new_lines.append(f'{indent}\tlog.Printf("json unmarshal failed: %v", err)')
            new_lines.append(f'{indent}}}')
            continue
        
        new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    if content != original:
        if 'log.Printf' in content and '"log"' not in content:
            content = content.replace('import (', 'import (\n\t"log"', 1)
        
        with open(fp, 'w') as f:
            f.write(content)
        print(f"FIXED: {fname}")
        total += 1
    else:
        print(f"NO CHANGE: {fname}")

print(f"\nTotal modified: {total}")

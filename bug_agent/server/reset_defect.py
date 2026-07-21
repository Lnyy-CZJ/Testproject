import sqlite3, sys

conn = sqlite3.connect('/Users/jame/Workspace/bug_agent/server/bug_agent.db')
c = conn.cursor()

# Check current state
c.execute("SELECT id, status FROM defects WHERE id=35")
row = c.fetchone()
print(f"Defect 35: id={row[0]}, status={row[1]}")

# Reset status to pending_analysis
c.execute("UPDATE defects SET status='pending_analysis' WHERE id=35")
conn.commit()
print(f"Status updated to pending_analysis")

# Delete corrupted reports
c.execute("DELETE FROM analysis_reports WHERE defect_id=35")
deleted = c.rowcount
print(f"Deleted {deleted} reports")

# Delete fix tasks
c.execute("DELETE FROM fix_tasks WHERE defect_id=35")
deleted = c.rowcount
print(f"Deleted {deleted} fix tasks")

# Verify
c.execute("SELECT id, status FROM defects WHERE id=35")
row = c.fetchone()
print(f"Verified: id={row[0]}, status={row[1]}")

c.execute("SELECT count(*) FROM analysis_reports WHERE defect_id=35")
print(f"Remaining reports: {c.fetchone()[0]}")

c.execute("SELECT count(*) FROM fix_tasks WHERE defect_id=35")
print(f"Remaining fix_tasks: {c.fetchone()[0]}")

conn.close()

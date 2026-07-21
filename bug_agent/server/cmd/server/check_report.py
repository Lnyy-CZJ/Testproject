import json

with open('/tmp/report40.json') as f:
    data = json.load(f)

inner = data.get('data', {})
report = inner.get('report', inner)
print("Inner keys:", list(inner.keys()))
print("Report keys:", list(report.keys()))

analysis = report.get('analysis', '')
print(f"Analysis type: {type(analysis).__name__}, length: {len(str(analysis))}")
if isinstance(analysis, str) and analysis:
    print("ANALYSIS:", analysis[:3000])
elif analysis:
    print("ANALYSIS:", json.dumps(analysis, ensure_ascii=False)[:3000])
else:
    print("ANALYSIS is empty/None")

solution = report.get('solution', '')
if isinstance(solution, str) and solution:
    print("SOLUTION:", solution[:1000])
elif solution:
    print("SOLUTION:", json.dumps(solution, ensure_ascii=False)[:1000])
else:
    print("SOLUTION is empty/None")

print(f"Report status: {report.get('status')}")
print(f"Report agentType: {report.get('agentType')}")
print(f"Report failureReason: {report.get('failureReason', 'N/A')}")
print(f"Report riskSummary: {report.get('riskSummary', 'N/A')}")

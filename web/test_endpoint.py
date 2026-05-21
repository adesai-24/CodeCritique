"""Quick smoke-test for the /api/review endpoint."""
import sys
import json
import requests

CODE = '''import subprocess
import hashlib

def run_cmd(user_input):
    subprocess.run(user_input, shell=True)

password = "hunter2"
hashlib.md5(b"data").hexdigest()

x=1;y=2
import os,sys
'''

def main():
    try:
        resp = requests.post(
            "http://localhost:8001/api/review",
            json={"code": CODE, "filename": "demo.py", "language": "python"},
            stream=True,
            timeout=120,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    event_type = "message"
    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.decode()
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if event_type == "status":
                print(f"  [status]  {data['message']}")
            elif event_type == "checker_done":
                print(f"  [done]    {data['checker']} — {data['count']} issues")
            elif event_type == "issues":
                print(f"  [issues]  {len(data)} total")
                for i in data[:5]:
                    print(f"            {i['severity']:8s} L{i['line']}: {i['message'][:65]}")
            elif event_type == "synthesis":
                print(f"  [synth]   summary: {str(data.get('summary', ''))[:90]}")
                print(f"            critical={data.get('critical')} warnings={data.get('warnings')}")
            elif event_type == "complete":
                d = data
                status = "PASS" if d["passed"] else "BLOCKED"
                print(f"  [{status}]   total={d['total']} fatal={d['fatal']} warn={d['warnings']} info={d['info']}")
            elif event_type == "ai_error":
                print(f"  [ai_err]  {data.get('error')}")


if __name__ == "__main__":
    main()

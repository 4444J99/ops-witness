import os, json, urllib.request

token = None  # allow-secret
env_file = "/Users/4jp/Workspace/ops-witness/scripts/.github-mcp.env"
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            if line.startswith("GITHUB_PERSONAL_ACCESS_TOKEN="):
                token = line.strip().split("=", 1)[1].strip('"\'')  # allow-secret

repos = [
    ("organvm-iii-ergon", "public-record-data-scrapper"),
    ("organvm", "organvm-corpvs-testamentvm"),
    ("4444J99", "peer-audited--behavioral-blockchain"),
    ("a-organvm", "post-dsp-platform"),
    ("organvm-iii-ergon", "charles-universe")
]

results = []
for owner, repo in repos:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues?labels=jules&state=all&sort=created&direction=desc&per_page=5"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "Gemini-Orchestrator")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            results.append({
                "repo": f"{owner}/{repo}",
                "issues": [
                    {
                        "number": i["number"],
                        "title": i["title"],
                        "state": i["state"],
                        "html_url": i["html_url"],
                        "comments": i["comments"],
                        "created_at": i["created_at"]
                    } for i in data
                ]
            })
    except Exception as e:
        results.append({"repo": f"{owner}/{repo}", "error": str(e)})

pr_results = []
for owner, repo in repos:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&sort=created&direction=desc&per_page=5"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "Gemini-Orchestrator")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            pr_results.append({
                "repo": f"{owner}/{repo}",
                "prs": [
                    {
                        "number": p["number"],
                        "title": p["title"],
                        "user": p["user"]["login"],
                        "head": p["head"]["ref"],
                        "html_url": p["html_url"],
                        "created_at": p["created_at"]
                    } for p in data
                ]
            })
    except Exception as e:
        pr_results.append({"repo": f"{owner}/{repo}", "error": str(e)})

print("=== ISSUES ===")
print(json.dumps(results, indent=2))
print("=== PULL REQUESTS ===")
print(json.dumps(pr_results, indent=2))

import os
import re
import requests
import pandas as pd

def extract_duration(body: str) -> str | None:
    if not body:
        return None

    # 1) Prosty klucz-wartość: "Duration: 3h" lub "Duration - 3h"
    m = re.search(r"(?im)^\s*Duration\s*[:\-]\s*(.+?)\s*$", body)
    if m:
        return m.group(1).strip()

    # 2) Sekcja z formularza: "### Duration" i pierwsza niepusta linia poniżej
    sec = re.search(r"(?is)^\s*#{2,3}\s*Duration\s*$([\s\S]+?)^(?:#{2,3}\s|\Z)", body, re.MULTILINE)
    if sec:
        # weź pierwszą niepustą linię w sekcji
        for line in sec.group(1).splitlines():
            line = line.strip()
            if line:
                # Usuń ewentualne markdownowe wypełniacze
                line = re.sub(r"^>\s*", "", line)     # cytaty
                line = re.sub(r"^\*\*\s*|\s*\*\*$", "", line)  # pogrubienia
                return line.strip()

    return None

owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
token = os.environ["GH_TOKEN"]

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

base_url = f"https://api.github.com/repos/{owner}/{repo}/issues"

issues = []
page = 1

while True:
    resp = requests.get(
        base_url,
        headers=headers,
        params={"state": "all", "per_page": 100, "page": page},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        break

    for it in data:
        # pomiń PR-y
        if "pull_request" in it:
            continue

        body = it.get("body") or ""
        duration = extract_duration(body)

        issues.append({
            "number": it.get("number"),
            "title": it.get("title"),
            "state": it.get("state"),
            "labels": ",".join(l["name"] for l in it.get("labels", [])),
            "assignees": ",".join(a["login"] for a in it.get("assignees", [])),
            "milestone": (it.get("milestone") or {}).get("title"),
            "created_at": it.get("created_at"),
            "updated_at": it.get("updated_at"),
            "closed_at": it.get("closed_at"),
            "author": (it.get("user") or {}).get("login"),
            "url": it.get("html_url"),
            "duration": duration,  # NOWA KOLUMNA
        })
    page += 1

df = pd.DataFrame(issues)
# opcjonalnie: ustaw kolumny w pożądanej kolejności
cols = ["number","title","state","duration","labels","assignees","milestone","created_at","updated_at","closed_at","author","url"]
df = df.reindex(columns=cols)
df.to_csv("issues_export.csv", index=False)
print(f"Exported {len(issues)} issues -> issues_export.csv (with 'duration')")

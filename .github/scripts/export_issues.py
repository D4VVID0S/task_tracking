import os
import requests
import pandas as pd

token = os.environ["GH_TOKEN"]
owner = os.environ["OWNER"]
repo = os.environ["REPO"]
view_name = os.environ["VIEW_NAME"]

headers = {"Authorization": f"Bearer {token}"}
url = "https://api.github.com/repos/{}/{}/issues".format(owner, repo)

# pobranie issues
issues = []
page = 1
while True:
    resp = requests.get(url, headers=headers, params={"state": "all", "per_page": 100, "page": page})
    data = resp.json()
    if not data:
        break
    for issue in data:
        if "pull_request" not in issue:  # wyklucz PR-y
            issues.append({
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "created_at": issue["created_at"],
                "updated_at": issue["updated_at"],
                "url": issue["html_url"],
            })
    page += 1

df = pd.DataFrame(issues)
df.to_csv("issues_export.csv", index=False)
print(f"Exported {len(issues)} issues to issues_export.csv")

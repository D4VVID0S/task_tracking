import os
import requests
import pandas as pd

token = os.environ["GH_TOKEN"]
owner, repo = os.environ["REPO_FULL"].split("/", 1)
project_number = os.environ.get("PROJECT_NUMBER")  # opcjonalnie
project_owner = os.environ.get("PROJECT_OWNER", owner)

REST_HEADERS = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
GQL_HEADERS = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
}

def fetch_all_issues(owner: str, repo: str):
    """Pobiera WSZYSTKIE issues (bez PR) z repo, ze standardowymi polami."""
    base_url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    issues = []
    page = 1
    while True:
        r = requests.get(
            base_url,
            headers=REST_HEADERS,
            params={"state": "all", "per_page": 100, "page": page},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for it in batch:
            if "pull_request" in it:  # pomiń PR-y
                continue

            reactions = it.get("reactions") or {}
            issues.append({
                # podstawa
                "number": it.get("number"),
                "title": it.get("title"),
                "state": it.get("state"),
                "created_at": it.get("created_at"),
                "updated_at": it.get("updated_at"),
                "closed_at": it.get("closed_at"),
                "url": it.get("html_url"),
                # dodatkowe, często potrzebne:
                "body": (it.get("body") or "").replace("\r\n", "\n"),
                "author": (it.get("user") or {}).get("login"),
                "assignees": ",".join(a["login"] for a in it.get("assignees", [])),
                "labels": ",".join(l["name"] for l in it.get("labels", [])),
                "milestone": (it.get("milestone") or {}).get("title"),
                "comments_count": it.get("comments"),
                "locked": it.get("locked"),
                "node_id": it.get("node_id"),  # potrzebne do GraphQL ProjectV2
                # szybkie podsumowanie reakcji (jeśli API zwróciło):
                "reactions_+1": reactions.get("+1"),
                "reactions_-1": reactions.get("-1"),
                "reactions_laugh": reactions.get("laugh"),
                "reactions_hooray": reactions.get("hooray"),
                "reactions_confused": reactions.get("confused"),
                "reactions_heart": reactions.get("heart"),
                "reactions_rocket": reactions.get("rocket"),
                "reactions_eyes": reactions.get("eyes"),
            })
        page += 1
    return issues

def gql(query: str, variables: dict):
    r = requests.post(
        "https://api.github.com/graphql",
        headers=GQL_HEADERS,
        json={"query": query, "variables": variables},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]

def fetch_project_field_map(project_owner: str, project_number: int):
    """Pobiera mapę pól (id->nazwa, typ) dla ProjectV2."""
    query = """
    query($login:String!, $number:Int!) {
      user(login:$login) { projectV2(number:$number) { id title fields(first:100) {
        nodes {
          id
          name
          dataType
          ... on ProjectV2Field { id name dataType }
          ... on ProjectV2SingleSelectField { id name dataType options { id name } }
        }
      }}}
      organization(login:$login) { projectV2(number:$number) { id title fields(first:100) {
        nodes {
          id
          name
          dataType
          ... on ProjectV2Field { id name dataType }
          ... on ProjectV2SingleSelectField { id name dataType options { id name } }
        }
      }}}
    }
    """
    d = gql(query, {"login": project_owner, "number": int(project_number)})
    proj = (d.get("user") or {}).get("projectV2") or (d.get("organization") or {}).get("projectV2")
    if not proj:
        raise RuntimeError(f"ProjectV2 {project_owner} #{project_number} nie znaleziony")
    field_map = {}
    for f in proj["fields"]["nodes"]:
        field_map[f["id"]] = {
            "name": f["name"],
            "dataType": f["dataType"],
            "options": {o["id"]: o["name"] for o in (f.get("options") or [])},
        }
    return field_map

def fetch_issue_project_fields(issue_node_id: str, project_number: int, field_map: dict):
    """
    Dla pojedynczego issue pobiera wartości pól z WYBRANEGO ProjectV2 (po number),
    zwraca dict {field_name: value}.
    """
    query = """
    query($id:ID!, $projectNumber:Int!) {
      node(id:$id) {
        ... on Issue {
          projectItems(first:50, includeArchived:false) {
            nodes {
              project { number title }
              fieldValues(first:100) {
                nodes {
                  __typename
                  field { ... on ProjectV2FieldCommon { id name } }
                  ... on ProjectV2ItemFieldTextValue { text }
                  ... on ProjectV2ItemFieldNumberValue { number }
                  ... on ProjectV2ItemFieldDateValue { date }
                  ... on ProjectV2ItemFieldSingleSelectValue { optionId }
                  ... on ProjectV2ItemFieldIterationValue { title }
                  ... on ProjectV2ItemFieldMilestoneValue { milestone { title } }
                  ... on ProjectV2ItemFieldRepositoryValue { repository { nameWithOwner } }
                  ... on ProjectV2ItemFieldPullRequestValue { pullRequests(first:5){ nodes{ number } } }
                }
              }
            }
          }
        }
      }
    }
    """
    d = gql(query, {"id": issue_node_id, "projectNumber": int(project_number)})

    node = d.get("node")
    if not node:
        return {}

    # znajdź item należący do danego projektu (po number)
    items = (node.get("projectItems") or {}).get("nodes") or []
    target_item = None
    for it in items:
        prj = it.get("project") or {}
        if prj.get("number") == int(project_number):
            target_item = it
            break
    if not target_item:
        return {}

    values = target_item.get("fieldValues", {}).get("nodes") or []
    out = {}
    for v in values:
        field = (v.get("field") or {})
        fid = field.get("id")
        fname = field.get("name") or (field_map.get(fid) or {}).get("name") or fid

        t = v.get("__typename")
        if t == "ProjectV2ItemFieldTextValue":
            out[fname] = v.get("text")
        elif t == "ProjectV2ItemFieldNumberValue":
            out[fname] = v.get("number")
        elif t == "ProjectV2ItemFieldDateValue":
            out[fname] = v.get("date")
        elif t == "ProjectV2ItemFieldSingleSelectValue":
            opt_id = v.get("optionId")
            out[fname] = (field_map.get(fid, {}).get("options", {}) or {}).get(opt_id, opt_id)
        elif t == "ProjectV2ItemFieldIterationValue":
            out[fname] = v.get("title")
        elif t == "ProjectV2ItemFieldMilestoneValue":
            out[fname] = (v.get("milestone") or {}).get("title")
        elif t == "ProjectV2ItemFieldRepositoryValue":
            out[fname] = (v.get("repository") or {}).get("nameWithOwner")
        elif t == "ProjectV2ItemFieldPullRequestValue":
            prs = (v.get("pullRequests") or {}).get("nodes") or []
            out[fname] = ",".join(f"#{p['number']}" for p in prs if p and p.get("number"))
        else:
            # inne typy — zapisz surowo
            out[fname] = None
    return out

def main():
    rows = fetch_all_issues(owner, repo)

    # jeśli podany PROJECT_NUMBER — dorzuć pola ProjectV2
    if project_number:
        field_map = fetch_project_field_map(project_owner, int(project_number))
        # zbuduj dynamiczny zestaw kolumn (łączny dla wszystkich issues)
        extra_cols = set()
        project_values_per_issue = []
        for it in rows:
            vals = fetch_issue_project_fields(it["node_id"], int(project_number), field_map)
            project_values_per_issue.append(vals)
            extra_cols.update(vals.keys())

        # scal do jednego rekordu / wiersza
        for it, vals in zip(rows, project_values_per_issue):
            for col in extra_cols:
                it[f"proj_{col}"] = vals.get(col)

    # finalny DataFrame
    df = pd.DataFrame(rows)

    # domyślne kolumny na start (jeżeli istnieją), potem reszta
    first_cols = [
        "number", "title", "state", "created_at", "updated_at", "url",
        "author", "assignees", "labels", "milestone", "comments_count",
        "closed_at", "locked",
        "reactions_+1", "reactions_-1", "reactions_laugh", "reactions_hooray",
        "reactions_confused", "reactions_heart", "reactions_rocket", "reactions_eyes",
        "body",
    ]
    cols = [c for c in first_cols if c in df.columns] + [c for c in df.columns if c not in first_cols + ["node_id"]]
    df = df[cols]

    df.to_csv("issues_export.csv", index=False)
    print(f"Exported {len(df)} issues -> issues_export.csv")

if __name__ == "__main__":
    main()

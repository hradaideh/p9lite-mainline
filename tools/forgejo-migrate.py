#!/usr/bin/env python3
"""Push every git working copy under ~ to the phone's Forgejo (private repos, push-to-create).
  forgejo-migrate.py REPOLIST [--dry-run]
REPOLIST: one path per line relative to ~ (e.g. find output). Naming:
  ~/sourcegit/<name>            -> hradaideh/<name>
  ~/sourcegit/<org>/<a>/<b>     -> <org>/<a>-<b>        (org created private if missing)
  ~/<x>/<y> (outside sourcegit) -> hradaideh/<x>-<y>
Pushes local branches and tags only (--no-verify: no repo hooks run; LFS objects are not uploaded).
Token is read from ~/p9lite-backups/forgejo-admin.txt; git goes over SSH (port 2222) via the USB link."""
import json, os, re, subprocess, sys, urllib.request

HOST, USER = "172.16.42.1", "hradaideh"
API = "http://%s:3000/api/v1" % HOST
HOME = os.path.expanduser("~")
TOKEN = dict(l.strip().split("=", 1) for l in open(HOME + "/p9lite-backups/forgejo-admin.txt") if "=" in l)["token"]
SSH = "ssh -p 2222 -i %s/.ssh/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes" % HOME


def clean(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "-", s).strip(".-") or "repo"


def target(rel):
    parts = rel.split("/")
    if parts[0] == "sourcegit" and len(parts) > 2:
        return clean(parts[1]), clean("-".join(parts[2:]))
    if parts[0] == "sourcegit":
        return USER, clean(parts[1])
    return USER, clean("-".join(parts))


def api(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": "token " + TOKEN, "Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


def git(path, *args):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True,
                       env=dict(os.environ, GIT_SSH_COMMAND=SSH, GIT_TERMINAL_PROMPT="0"))
    return r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]


def main():
    rels = [r for r in (l.strip().removeprefix("./") for l in open(sys.argv[1])) if r and not r.startswith(".")]
    dry = "--dry-run" in sys.argv
    seen, orgs, ok, failed = {}, set(), 0, []
    for rel in rels:
        owner, name = target(rel)
        if (owner, name) in seen:
            name = clean(name + "-" + str(len(seen)))
        seen[(owner, name)] = rel
        if dry:
            print("%-60s -> %s/%s" % (rel, owner, name)); continue
        if owner != USER and owner not in orgs:
            api("POST", "/orgs", {"username": owner, "visibility": "private"})
            orgs.add(owner)
        path = os.path.join(HOME, rel)
        if subprocess.run(["git", "-C", path, "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode:
            failed.append((rel, "no commits")); print("SKIP", rel, "(no commits)", flush=True); continue
        url = "ssh://git@%s:2222/%s/%s.git" % (HOST, owner, name)
        rc, msg = git(path, "push", "--no-verify", "--all", url)
        if rc == 0:
            rc, msg = git(path, "push", "--no-verify", "--tags", url)
        if rc == 0:
            ok += 1; print("OK  ", rel, "->", owner + "/" + name, flush=True)
        else:
            failed.append((rel, msg[0])); print("FAIL", rel, msg[0], flush=True)
    if not dry:
        print("\n%d pushed, %d failed" % (ok, len(failed)))
        for rel, why in failed:
            print("  %s: %s" % (rel, why))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Refuse any commit whose staged content contains something shaped like a credential.

Not a reminder, a gate. Keys have reached this project three times in ways nobody planned:
early runs passed them as command-line arguments and 78 copies ended up in pipeline_log.txt;
a variability run was invoked with a key where a variable name belonged, putting it in shell
history and terminal output; and the CORE key cannot be rotated at all, because it is issued
against an institutional subscription with no self-service dashboard. When rotation is not
always available, "remember not to commit it" is not a control.

So this scans what is actually staged -- not the working tree, not the last commit -- and exits
non-zero on a match, naming the file and line without printing the value.

Install once:

    git config core.hooksPath scripts/hooks

That path is committed, so every clone gets the hook by pointing at it. Nothing here can be
bypassed accidentally; `git commit --no-verify` still skips it, which is deliberate -- a gate
you cannot override becomes a gate people work around.
"""
import re
import subprocess
import sys

# Shapes, not values. Each is a provider's own documented prefix, or a flag handing a long
# opaque string to something that wants a secret.
PATTERNS = [
    ("OpenAI / OpenRouter key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("Slack token", re.compile(r"xox[abprs]-[0-9A-Za-z-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # A credential-ish name assigned a long opaque literal. Deliberately narrow: it wants an
    # assignment or a flag, so prose about keys and a 40-character git sha do not trip it.
    ("secret assigned inline",
     re.compile(r"(?i)(api[_-]?key|secret|passwd|password|token|bearer)"
                r"\s*(?:[:=]|=>)\s*[\"']?([A-Za-z0-9/+_-]{24,})[\"']?")),
    ("secret on a command line",
     re.compile(r"--(?:[a-z-]*-)?(?:api-key|token|secret|password)[= ]+(\S{24,})")),
]

#: Long hex strings are hashes, not secrets -- sha256 digests, git revisions, content ids.
HEXISH = re.compile(r"^[a-f0-9]{24,}$")

#: Paths whose whole purpose is to describe this problem. Excluded so documentation about
#: credential handling cannot block a commit about credential handling.
ALLOW_PATHS = (
    "scripts/hooks/pre-commit",
    "scripts/hooks/pre_commit_check.py",
    "scripts/scrub_log_keys.py",
)


def staged_diff():
    return subprocess.run(["git", "diff", "--cached", "--unified=0", "--no-color"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def main():
    path = None
    findings = []
    for line in staged_diff().splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if path in ALLOW_PATHS:
            continue
        added = line[1:]
        for label, pattern in PATTERNS:
            m = pattern.search(added)
            if not m:
                continue
            captured = m.group(m.lastindex or 0)
            if HEXISH.match(captured):
                continue
            findings.append((path, label, len(captured)))
            break

    if not findings:
        return 0

    print("COMMIT REFUSED: staged content looks like it contains a credential.\n")
    for path, label, length in findings:
        print("  %-28s %s (%d chars, not shown)" % (label, path, length))
    print("\nThe value is not printed here on purpose. If it is a real credential:")
    print("  - do not commit it, and remove it from the staged content")
    print("  - assume it is already exposed: it is in your shell history or editor buffer")
    print("\nIf this is a false positive -- a test fixture, an example, a hash this hook")
    print("mistook for a secret -- add the path to ALLOW_PATHS in pre_commit_check.py,")
    print("or commit with --no-verify if you are certain.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

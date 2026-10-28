"""Auditoria local e heurística; nunca imprime conteúdo nem altera o histórico."""

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent

# Literais já conferidos nos testes de rejeição de URLs. A exceção é exata;
# outra credencial no mesmo arquivo continua sendo sinalizada.
SYNTHETIC_URLS = {
    "tests/test_gateway_config.py": b"https://" + b"user:password@gateway.test",
    "tests/test_vector_store.py": b"https://" + b"user:private@qdrant.test",
}

# Padrões específicos evitam tratar texto de instruções como credencial real.
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_token": re.compile(rb"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b"),
    "jwt_literal": re.compile(rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
    "credential_url": re.compile(rb"https?://[^\s/:]+:[^\s/@]+@"),
}
ASSIGNMENT = re.compile(rb'''(?im)^[ \t]*(?:export[ \t]+)?(?:LLM_API_KEY|QDRANT_API_KEY|API_ACCESS_TOKEN)[ \t]*=[ \t]*["']?([^\s"']+)''')


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def findings(path: str, content: bytes) -> list[str]:
    parts = Path(path).parts
    lower = path.lower()
    issues = []
    if ("data" in parts or any(p in {".aws", ".agents", ".codex"} for p in parts)
            or (Path(path).name.startswith(".env") and Path(path).name != ".env.example")
            or lower.endswith((".pdf", ".pem", ".key", ".npy", ".npz", ".sqlite", ".sqlite3", ".db"))):
        issues.append("private_artifact_path")
    if content.startswith(b"%PDF-"):
        issues.append("pdf_content")
    scanned = content.replace(SYNTHETIC_URLS[path], b"https://synthetic.test") if path in SYNTHETIC_URLS else content
    issues.extend(name for name, pattern in SECRET_PATTERNS.items() if pattern.search(scanned))
    for match in ASSIGNMENT.finditer(content):
        value = match[1].lower()
        if value and not value.startswith((b"$", b"<", b"synthetic", b"example", b"your_", b"sua_", b"replace", b"test", b"changeme")):
            issues.append("credential_assignment_requires_review")
            break
    return sorted(set(issues))


def audit() -> dict[str, object]:
    records = []
    inspected = set()
    # Inclui todos os blobs alcançáveis por refs e reflogs disponíveis localmente.
    commits = git("rev-list", "--all", "--reflog").decode().splitlines()
    for commit in commits:
        for entry in git("ls-tree", "-r", "-z", commit).split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, oid = metadata.decode().split()
            path = raw_path.decode("utf-8", errors="replace")
            if kind != "blob" or (oid, path) in inspected:
                continue
            inspected.add((oid, path))
            issues = findings(path, git("cat-file", "blob", oid))
            if issues:
                records.append({"scope": "history", "object": oid, "path": path, "rules": issues})
    index = git("ls-files", "--stage", "-z").split(b"\0")
    index_count = 0
    for entry in index:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        _, oid, _ = metadata.decode().split()
        path = raw_path.decode("utf-8", errors="replace")
        index_count += 1
        issues = findings(path, git("cat-file", "blob", oid))
        if issues:
            records.append({"scope": "index", "path": path, "rules": issues})
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    working_count = 0
    for raw_path in sorted(set(paths) - {b""}):
        path = raw_path.decode("utf-8", errors="replace")
        target = ROOT / path
        if target.is_file() and not target.is_symlink():
            working_count += 1
            issues = findings(path, target.read_bytes())
            if issues:
                records.append({"scope": "working_tree", "path": path, "rules": issues})
    return {"status": "findings" if records else "no_findings", "commits": len(commits),
            "historical_blob_paths": len(inspected), "index_files": index_count, "working_files": working_count,
            "findings": records,
            "reviewed_synthetic_urls": sorted(SYNTHETIC_URLS),
            "limitations": "Heurística local; não verifica validade de credenciais, objetos inacessíveis, remotos não buscados ou formatos desconhecidos."}


def main() -> int:
    try:
        report = audit()
    except Exception:
        report = {"status": "failed", "error": "git_audit_failed"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "no_findings" else 1


if __name__ == "__main__":
    raise SystemExit(main())

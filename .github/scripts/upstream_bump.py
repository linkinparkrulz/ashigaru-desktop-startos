#!/usr/bin/env python3
"""Bump the package to the latest signed Ashigaru Desktop release.

Run by .github/workflows/upstream-watch.yml. It changes nothing unless the
latest published upstream release is newer than the Dockerfile's pin and its
signature chain verifies:

  RELEASE-BIP47-SIGNATURE.txt  signed by the pinned release notification address
    -> covers MESSAGE.txt      byte for byte
    -> MESSAGE.txt names this repo, version and tag, and SHA256(SHA256SUMS)
    -> SHA256SUMS              lists the x86_64 AppImage the Dockerfile fetches

Only then does it write the new version and SHA256SUMS hash into the
Dockerfile and startos/versions/current.ts. The build re-checks the
AppImage against SHA256SUMS, and SHA256SUMS against the pinned hash.

Exit status: 0 with "updated" or "up-to-date" on stdout, non-zero on any
verification failure. With --dry-run nothing is written.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from coincurve import PublicKey

UPSTREAM = "linkinparkrulz/ashigaru-desktop"
# Notification address of the release-signing BIP47 payment code
# PM8TJM51x2mDd85CzEgVc2y7vdyB3eBj93JVjVtCt6PZtmfzhFzYPMXYBXh28zthWhVKGjVQZPT1MKxGxEtfenLYEkuc5GhoWtMzQCF8c8mrckYFM7r1,
# as published in the upstream README.
SIGNING_ADDRESS = "1K8CDoBYWBuaeAhejLAk5hiACAgbbPnDCJ"

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
LOCALES = ("en_US", "es_ES", "de_DE", "pl_PL", "fr_FR")
NOTES = {
    "en_US": "Updated Ashigaru Desktop to {v}. [Full release notes]({url})",
    "es_ES": "Ashigaru Desktop actualizado a {v}. [Notas completas de la versión]({url})",
    "de_DE": "Ashigaru Desktop auf {v} aktualisiert. [Vollständige Versionshinweise]({url})",
    "pl_PL": "Zaktualizowano Ashigaru Desktop do wersji {v}. [Pełne informacje o wydaniu]({url})",
    "fr_FR": "Ashigaru Desktop mis à jour vers la version {v}. [Notes de version complètes]({url})",
}


class VerifyError(Exception):
    pass


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ashigaru-desktop-startos-upstream-watch"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def version_tuple(v: str) -> tuple:
    if not re.fullmatch(r"\d+(\.\d+)*", v):
        raise VerifyError(f"unexpected version format: {v!r}")
    return tuple(int(p) for p in v.split("."))


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def base58check(payload: bytes) -> str:
    data = payload + sha256(sha256(payload))[:4]
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + out


def _ripemd160_py(data: bytes) -> bytes:
    """RIPEMD-160 for OpenSSL builds that leave it out of hashlib."""
    def rol(x, n):
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

    def f(j, x, y, z):
        if j < 16:
            return x ^ y ^ z
        if j < 32:
            return (x & y) | (~x & z)
        if j < 48:
            return (x | ~y) ^ z
        if j < 64:
            return (x & z) | (y & ~z)
        return x ^ (y | ~z)

    r1 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
          3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12, 1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
          4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13]
    r2 = [5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12, 6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
          15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13, 8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
          12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11]
    s1 = [11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8, 7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
          11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5, 11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
          9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6]
    s2 = [8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6, 9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
          9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5, 15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
          8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11]
    k1 = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E]
    k2 = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000]

    h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]
    msg = data + b"\x80" + b"\0" * ((55 - len(data)) % 64) + (len(data) * 8).to_bytes(8, "little")
    for off in range(0, len(msg), 64):
        x = [int.from_bytes(msg[off + 4 * i: off + 4 * i + 4], "little") for i in range(16)]
        al, bl, cl, dl, el = h
        ar, br, cr, dr, er = h
        for j in range(80):
            t = rol((al + f(j, bl, cl, dl) + x[r1[j]] + k1[j // 16]) & 0xFFFFFFFF, s1[j]) + el
            al, el, dl, cl, bl = el, dl, rol(cl, 10), bl, t & 0xFFFFFFFF
            t = rol((ar + f(79 - j, br, cr, dr) + x[r2[j]] + k2[j // 16]) & 0xFFFFFFFF, s2[j]) + er
            ar, er, dr, cr, br = er, dr, rol(cr, 10), br, t & 0xFFFFFFFF
        t = (h[1] + cl + dr) & 0xFFFFFFFF
        h[1] = (h[2] + dl + er) & 0xFFFFFFFF
        h[2] = (h[3] + el + ar) & 0xFFFFFFFF
        h[3] = (h[4] + al + br) & 0xFFFFFFFF
        h[4] = (h[0] + bl + cr) & 0xFFFFFFFF
        h[0] = t
    return b"".join(v.to_bytes(4, "little") for v in h)


def ripemd160(data: bytes) -> bytes:
    try:
        return hashlib.new("ripemd160", data).digest()
    except ValueError:
        return _ripemd160_py(data)


def p2pkh(pubkey: bytes) -> str:
    return base58check(b"\x00" + ripemd160(sha256(pubkey)))


def varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    return b"\xfe" + n.to_bytes(4, "little")


def message_hash(message: bytes) -> bytes:
    prefix = b"\x18Bitcoin Signed Message:\n"
    return sha256(sha256(prefix + varint(len(message)) + message))


def recover_address(message: bytes, signature_b64: str) -> str:
    sig = base64.b64decode(signature_b64, validate=True)
    if len(sig) != 65 or not 27 <= sig[0] <= 34:
        raise VerifyError("signature is not a 65-byte compact Bitcoin message signature")
    header = sig[0] - 27
    compressed = header >= 4
    recid = header & 3
    recoverable = sig[1:] + bytes([recid])
    pub = PublicKey.from_signature_and_message(recoverable, message_hash(message), hasher=None)
    return p2pkh(pub.format(compressed=compressed))


def parse_signed_block(text: str) -> tuple:
    m = re.fullmatch(
        r"-----BEGIN BITCOIN SIGNED MESSAGE-----\r?\n(?P<msg>.*?)\r?\n"
        r"-----BEGIN BITCOIN SIGNATURE-----\r?\n(?P<sig>.*?)\r?\n?"
        r"-----END BITCOIN SIGNATURE-----\s*",
        text,
        re.S,
    )
    if not m:
        raise VerifyError("RELEASE-BIP47-SIGNATURE.txt is not a Bitcoin signed message block")
    lines = [line.strip() for line in m.group("sig").splitlines() if line.strip()]
    address = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("Address:")), None)
    sig_lines = [line for line in lines if ":" not in line]
    if address is None or len(sig_lines) != 1:
        raise VerifyError("signature block has no Address: line or no single base64 signature")
    return m.group("msg"), address, sig_lines[0]


def verify_release(tag: str, message_txt: bytes, signature_txt: bytes, sums: bytes) -> str:
    """Check the chain and return the SHA256SUMS hash to pin."""
    version = tag[1:] if tag.startswith("v") else tag
    signed_msg, address, signature = parse_signed_block(signature_txt.decode("utf-8"))

    # The block must carry MESSAGE.txt exactly; only MESSAGE.txt's own trailing
    # newline may differ, since a signed block cannot hold one.
    if signed_msg.encode("utf-8") != message_txt.rstrip(b"\r\n"):
        raise VerifyError("signed message differs from MESSAGE.txt")
    if address != SIGNING_ADDRESS:
        raise VerifyError(f"signed by {address}, expected {SIGNING_ADDRESS}")
    recovered = recover_address(signed_msg.encode("utf-8"), signature)
    if recovered != SIGNING_ADDRESS:
        raise VerifyError(f"signature recovers to {recovered}, expected {SIGNING_ADDRESS}")

    fields = dict(
        (k.strip(), v.strip())
        for k, v in (line.split(":", 1) for line in signed_msg.splitlines() if ":" in line)
    )
    expected = {"Repo": f"github.com/{UPSTREAM}", "Version": version, "Tag": tag}
    for key, want in expected.items():
        if fields.get(key) != want:
            raise VerifyError(f"MESSAGE.txt {key} is {fields.get(key)!r}, expected {want!r}")
    sums_hash = fields.get("SHA256(SHA256SUMS)", "")
    if not re.fullmatch(r"[0-9a-f]{64}", sums_hash):
        raise VerifyError("MESSAGE.txt has no SHA256(SHA256SUMS) line")
    if hashlib.sha256(sums).hexdigest() != sums_hash:
        raise VerifyError("SHA256SUMS does not match the hash in the signed message")

    appimage = f"Ashigaru-{version}-x86_64.AppImage"
    if not re.search(rf"^[0-9a-f]{{64}}  {re.escape(appimage)}$", sums.decode("utf-8"), re.M):
        raise VerifyError(f"SHA256SUMS does not list {appimage}")
    return sums_hash


def notes_block(version: str, url: str, indent: str) -> str:
    lines = [f"{indent}releaseNotes: {{"]
    for loc in LOCALES:
        lines.append(f"{indent}  {loc}: {json.dumps(NOTES[loc].format(v=version, url=url), ensure_ascii=False)},")
    lines.append(f"{indent}}},")
    return "\n".join(lines)


def update_current_ts(text: str, version: str, url: str) -> str:
    if not re.search(r"up:\s*async\s*\(\{\s*effects\s*\}\)\s*=>\s*\{\s*\}", text):
        raise VerifyError(
            "current.ts carries a migration: move that version to its own file before bumping"
        )
    text, n = re.subn(r"version:\s*'[^']*'", f"version: '{version}:0'", text, count=1)
    if n != 1:
        raise VerifyError("could not find version in current.ts")
    m = re.search(r"^(?P<indent>[ \t]*)releaseNotes:\s*\{", text, re.M)
    if not m:
        raise VerifyError("could not find releaseNotes in current.ts")
    end = text.index("\n" + m.group("indent") + "},", m.end())
    return text[: m.start()] + notes_block(version, url, m.group("indent")) + text[end + len(m.group("indent")) + 3 :]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="package repository root")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--body", help="write a pull request body here")
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = ap.parse_args()

    root = Path(args.repo)
    dockerfile = root / "Dockerfile"
    current_ts = root / "startos/versions/current.ts"
    docker = dockerfile.read_text()
    pinned = re.search(r"^ARG ASHIGARU_VERSION=(\S+)$", docker, re.M).group(1)

    rel = json.loads(fetch(f"https://api.github.com/repos/{UPSTREAM}/releases/latest"))
    tag = rel["tag_name"]
    version = tag[1:] if tag.startswith("v") else tag
    if rel.get("draft") or rel.get("prerelease") or version_tuple(version) <= version_tuple(pinned):
        print(f"up-to-date: pinned {pinned}, latest {tag}")
        return 0

    base = f"https://github.com/{UPSTREAM}/releases/download/{tag}"
    try:
        sums_hash = verify_release(
            tag,
            fetch(f"{base}/MESSAGE.txt"),
            fetch(f"{base}/RELEASE-BIP47-SIGNATURE.txt"),
            fetch(f"{base}/SHA256SUMS"),
        )
    except VerifyError as e:
        print(f"refusing {tag}: {e}", file=sys.stderr)
        return 1

    url = rel["html_url"]
    new_docker = re.sub(r"^ARG ASHIGARU_VERSION=\S+$", f"ARG ASHIGARU_VERSION={version}", docker, count=1, flags=re.M)
    new_docker = re.sub(
        r"^ARG ASHIGARU_SUMS_SHA256=\S+$", f"ARG ASHIGARU_SUMS_SHA256={sums_hash}", new_docker, count=1, flags=re.M
    )
    try:
        new_current = update_current_ts(current_ts.read_text(), version, url)
    except VerifyError as e:
        print(f"refusing {tag}: {e}", file=sys.stderr)
        return 1

    print(f"updated: {pinned} -> {version} (SHA256SUMS {sums_hash})")
    if args.dry_run:
        return 0
    dockerfile.write_text(new_docker)
    current_ts.write_text(new_current)

    if args.body:
        upstream_notes = (rel.get("body") or "").strip().replace("```", "~~~") or "(no release notes upstream)"
        Path(args.body).write_text(
            f"""Bumps Ashigaru Desktop from {pinned} to [{version}]({url}).

Verified before anything was written:
- `RELEASE-BIP47-SIGNATURE.txt` recovers to the release signing address `{SIGNING_ADDRESS}` and carries `MESSAGE.txt` exactly.
- `MESSAGE.txt` names `github.com/{UPSTREAM}`, version `{version}` and tag `{tag}`.
- `SHA256(SHA256SUMS)` is `{sums_hash}`, matching the downloaded `SHA256SUMS`, which lists `Ashigaru-{version}-x86_64.AppImage`.

Changes: `ASHIGARU_VERSION` and `ASHIGARU_SUMS_SHA256` in `Dockerfile`; `version` and templated `releaseNotes` in `startos/versions/current.ts`.

Before merging:
- [ ] Rewrite the release notes from the upstream notes below: the highlights a user notices, in all five locales, keeping the link.
- [ ] Build is green on this PR. If it didn't start, run **Build** on this branch from the Actions tab.
- [ ] Installed on StartOS: the desktop loads, a wallet opens, backup and restore work.
- [ ] After merging, tag `v{version}_0` on `main` to cut the GitHub Release.

<details><summary>Upstream release notes</summary>

Quoted as text, so its @mentions and links don't notify anyone from this PR.

```text
{upstream_notes}
```

</details>
"""
        )
    if args.github_output:
        with open(args.github_output, "a") as out:
            out.write(f"version={version}\nupdated=true\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

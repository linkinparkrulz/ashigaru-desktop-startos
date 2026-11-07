# Updating the upstream version

This package wraps the Ashigaru Desktop Linux release from `linkinparkrulz/ashigaru-desktop`. It installs the upstream `Ashigaru-<version>-x86_64.AppImage` (Linux releases ship only as an AppImage from 1.5.0) into a LinuxServer Selkies webtop image. The AppImage is checked against the release's `SHA256SUMS`, which is pinned by its own hash, then unpacked with `--appimage-extract`.

## Determining the upstream version

- **Ashigaru Desktop** (`linkinparkrulz/ashigaru-desktop`, https://github.com/linkinparkrulz/ashigaru-desktop):

  ```
  gh release view -R linkinparkrulz/ashigaru-desktop --json tagName -q .tagName
  ```

  Pinned as `ASHIGARU_VERSION` in `Dockerfile` (the tag is `v<version>`; the pin omits the `v`).

## Automated bump

The **Upstream watch** workflow (`.github/workflows/upstream-watch.yml`) runs daily and can also be started from the Actions tab. When the latest published upstream release is newer than `ASHIGARU_VERSION`, `.github/scripts/upstream_bump.py` checks the whole signature chain before writing anything:

- `RELEASE-BIP47-SIGNATURE.txt` must carry `MESSAGE.txt` exactly and recover to the release signing address `1K8CDoBYWBuaeAhejLAk5hiACAgbbPnDCJ`.
- `MESSAGE.txt` must name this upstream repository and the release's version and tag.
- `SHA256(SHA256SUMS)` must match the downloaded `SHA256SUMS`, which must list the AppImage.

Once those pass, it sets `ASHIGARU_VERSION` and `ASHIGARU_SUMS_SHA256` in `Dockerfile` and the version in `startos/versions/current.ts`, and opens a pull request from `upstream/v<version>`. The release notes it writes are a one-line placeholder: rewrite them from the upstream notes quoted in the pull request before merging. It refuses to bump while `current.ts` carries a migration; spin that version off into its own file first.

A pull request opened with the default token doesn't start **Build**. To have it start on its own, create a fine-grained personal access token for this repository only, with Contents and Pull requests set to read and write, and save it as the `UPSTREAM_BOT_TOKEN` Actions secret. Without it, run Build on the branch from the Actions tab.

The manual steps below remain the reference, and are what to follow if the workflow refuses a release.

## Applying the bump

- **Ashigaru Desktop**:
  1. Download the new release's `SHA256SUMS`, `MESSAGE.txt` and `RELEASE-BIP47-SIGNATURE.txt`.
  2. Verify the signature as the upstream README describes (**Tools → Verifier** in Ashigaru, or paymentcode.io/lab with the release signing payment code). The recovered signer must be `1K8CDoBYWBuaeAhejLAk5hiACAgbbPnDCJ`.
  3. Run `sha256sum SHA256SUMS` and confirm it matches the `SHA256(SHA256SUMS):` line in `MESSAGE.txt`.
  4. Set `ARG ASHIGARU_VERSION` and `ARG ASHIGARU_SUMS_SHA256` in `Dockerfile` to the new version and that hash.
  5. In `startos/versions/current.ts`, set `version` to `<version>:0` and rewrite `releaseNotes` in every locale. Spin the old version into its own file only if `current.ts` carries a migration.
  6. Once merged into `main`, tag the merge commit `v<version>` with `:` replaced by `_` (e.g. `v1.4.6_0`) and push the tag. The Release workflow builds the `.s9pk` and attaches it to a GitHub Release.

  The build re-checks the hash against `MESSAGE.txt` and the AppImage against `SHA256SUMS`, so a skipped step fails the build rather than shipping an unverified binary. The build downloads from the public release URL, so it fails while the upstream release is still a draft.

- **start-sdk**: pin an exact version (`npm install @start9labs/start-sdk@<version> --save-exact`), then run `npm install` again until `package-lock.json` stops changing. A bump can raise the minimum StartOS. After `make`, check `manifest.osVersion` (`node -e "console.log(require('./javascript/index.js').manifest.osVersion)"`), and if it rose, say so in the version's release notes: older StartOS doesn't enforce it on a sideload.

- **Selkies base image**: `Dockerfile` pins `ghcr.io/linuxserver/baseimage-selkies:debiantrixie` by release tag and digest, the same pin Start9's Bisq package uses. Verify the current tag with:

  ```
  docker buildx imagetools inspect ghcr.io/linuxserver/baseimage-selkies:debiantrixie
  ```

  When updating the base, pick the newest stable Debian Trixie release (skip `dev` tags) and replace both the tag and digest in the `FROM` line. Keep the flattened image's `ENV` block in sync with the base image's runtime environment, keeping `START_DOCKER=false`. Increment the StartOS downstream revision while keeping the Ashigaru version unchanged.

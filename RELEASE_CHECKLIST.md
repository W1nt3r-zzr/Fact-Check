# Release Checklist

Use this checklist whenever the browser extension and Railway backend must be released together.

## Version Rule

Use one version across all release surfaces:

- `browser-extension/manifest.json`
- `browser-extension/config.js`
- Git tag, for example `v2.0.2`
- GitHub Release, for example `v2.0.2`
- Railway deployment commit

Do not overwrite an existing GitHub Release for user-facing fixes. Publish a higher version so installed extensions can detect the update.

## Required Command

Run from the repository root:

```bash
scripts/release_browser_extension.sh 2.0.2
```

This verifies versions, runs tests, builds the ZIP, and checks the ZIP contains the queue-status frontend.

To publish after review:

```bash
scripts/release_browser_extension.sh 2.0.2 --publish
```

## Manual Checks

Before publishing:

- Confirm Chrome is loading `browser-extension`, not `extension`.
- Confirm no required files are untracked:

  ```bash
  git status --short browser-extension backend scripts RELEASE_CHECKLIST.md DEPLOYMENT.md
  ```

- Confirm the Railway backend exposes queue status:

  ```bash
  curl https://fact-check-production-8d0f.up.railway.app/api/v1/queue-status
  ```

After publishing:

- Reload the extension at `chrome://extensions/`.
- Refresh the tested webpage so the latest content script is injected.
- Run one fact check and confirm progress can show service load/queue state.


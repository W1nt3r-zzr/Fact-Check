const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const releaseScript = fs.readFileSync(
  path.join(__dirname, '../../scripts/release_browser_extension.sh'),
  'utf8',
);

test('release script can publish detailed release notes from a file', () => {
  assert.match(releaseScript, /RELEASE_NOTES_FILE/);
  assert.match(releaseScript, /--notes-file/);
  assert.doesNotMatch(releaseScript, /--notes "同步发布 browser-extension \$TAG 与后端队列状态支持。"/);
});

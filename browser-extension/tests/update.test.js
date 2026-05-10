const test = require('node:test');
const assert = require('node:assert/strict');

const {
  compareVersions,
  normalizeReleaseVersion,
  getUpdateStatus
} = require('../utils/update.js');

test('normalizeReleaseVersion removes release tag prefix', () => {
  assert.equal(normalizeReleaseVersion('v2.0.1'), '2.0.1');
  assert.equal(normalizeReleaseVersion('release-2.0.1'), '2.0.1');
});

test('compareVersions detects newer semantic version', () => {
  assert.equal(compareVersions('2.0.1', '2.0.0'), 1);
  assert.equal(compareVersions('2.0.0', '2.0.0'), 0);
  assert.equal(compareVersions('2.0.0', '2.1.0'), -1);
});

test('getUpdateStatus returns update details for newer GitHub release', () => {
  const status = getUpdateStatus({
    currentVersion: '2.0.0',
    release: {
      tag_name: 'v2.0.1',
      html_url: 'https://github.com/W1nt3r-zzr/Fact-Check/releases/tag/v2.0.1',
      assets: [
        {
          name: 'AI信息核查助手-v2.0.1.zip',
          browser_download_url: 'https://github.com/W1nt3r-zzr/Fact-Check/releases/download/v2.0.1/AI.zip'
        }
      ]
    }
  });

  assert.equal(status.hasUpdate, true);
  assert.equal(status.currentVersion, '2.0.0');
  assert.equal(status.latestVersion, '2.0.1');
  assert.equal(status.downloadUrl, 'https://github.com/W1nt3r-zzr/Fact-Check/releases/download/v2.0.1/AI.zip');
});

test('getUpdateStatus ignores same version GitHub release', () => {
  const status = getUpdateStatus({
    currentVersion: '2.0.0',
    release: {
      tag_name: 'v2.0.0',
      html_url: 'https://github.com/W1nt3r-zzr/Fact-Check/releases/tag/v2.0.0',
      assets: []
    }
  });

  assert.equal(status.hasUpdate, false);
  assert.equal(status.latestVersion, '2.0.0');
});

function normalizeReleaseVersion(value) {
  const match = String(value || '').match(/(\d+(?:\.\d+){0,2})/);
  return match ? match[1] : '';
}

function compareVersions(nextVersion, currentVersion) {
  const next = normalizeReleaseVersion(nextVersion).split('.').map(Number);
  const current = normalizeReleaseVersion(currentVersion).split('.').map(Number);
  const length = Math.max(next.length, current.length, 3);

  for (let i = 0; i < length; i += 1) {
    const nextPart = Number.isFinite(next[i]) ? next[i] : 0;
    const currentPart = Number.isFinite(current[i]) ? current[i] : 0;
    if (nextPart > currentPart) return 1;
    if (nextPart < currentPart) return -1;
  }
  return 0;
}

function selectReleaseDownloadUrl(release) {
  const assets = Array.isArray(release?.assets) ? release.assets : [];
  const zipAsset = assets.find((asset) => /\.zip$/i.test(asset?.name || ''));
  return zipAsset?.browser_download_url || release?.html_url || '';
}

function getUpdateStatus({ currentVersion, release }) {
  const latestVersion = normalizeReleaseVersion(release?.tag_name || release?.name);
  const normalizedCurrent = normalizeReleaseVersion(currentVersion);
  const hasUpdate = Boolean(latestVersion && compareVersions(latestVersion, normalizedCurrent) > 0);

  return {
    hasUpdate,
    currentVersion: normalizedCurrent,
    latestVersion,
    releaseUrl: release?.html_url || '',
    downloadUrl: hasUpdate ? selectReleaseDownloadUrl(release) : ''
  };
}

async function fetchLatestReleaseStatus(config, options = {}) {
  const updateConfig = config?.UPDATE_CHECK || {};
  if (updateConfig.enabled === false) {
    return { hasUpdate: false, currentVersion: normalizeReleaseVersion(config?.VERSION), latestVersion: '' };
  }

  const repo = updateConfig.repo;
  const apiUrl = updateConfig.apiUrl || (repo ? `https://api.github.com/repos/${repo}/releases/latest` : '');
  if (!apiUrl) {
    throw new Error('未配置 GitHub Release 检查地址');
  }

  const fetchImpl = options.fetchImpl || fetch;
  const response = await fetchImpl(apiUrl, {
    headers: { Accept: 'application/vnd.github+json' }
  });
  if (!response.ok) {
    throw new Error(`检查更新失败: ${response.status}`);
  }

  const release = await response.json();
  return getUpdateStatus({
    currentVersion: config?.VERSION,
    release
  });
}

if (typeof window !== 'undefined') {
  window.normalizeReleaseVersion = normalizeReleaseVersion;
  window.compareVersions = compareVersions;
  window.getUpdateStatus = getUpdateStatus;
  window.fetchLatestReleaseStatus = fetchLatestReleaseStatus;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    normalizeReleaseVersion,
    compareVersions,
    getUpdateStatus,
    fetchLatestReleaseStatus
  };
}

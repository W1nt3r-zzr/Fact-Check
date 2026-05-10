// Re-inject content assets into already-open tabs after the unpacked extension is reloaded.
// Chrome does not automatically re-run content scripts in existing pages on extension reload.

const CONTENT_SCRIPT_FILES = [
  'config.js',
  'utils/dom.js',
  'utils/markdown.js',
  'utils/highlight.js',
  'content/content.js'
];

const CONTENT_CSS_FILES = ['content/content.css'];

function canInjectIntoUrl(url = '') {
  return /^(https?|file):\/\//.test(url);
}

async function hasLiveContentScript(tabId) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { action: 'ping' });
    return response && response.ok === true;
  } catch (error) {
    return false;
  }
}

async function injectContentAssets(tabId) {
  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: CONTENT_CSS_FILES
    });
  } catch (error) {
    console.debug('CSS注入跳过:', error?.message || error);
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: CONTENT_SCRIPT_FILES
  });
}

async function ensureContentScript(tab) {
  if (!tab?.id || !canInjectIntoUrl(tab.url)) return;
  if (await hasLiveContentScript(tab.id)) return;

  try {
    await injectContentAssets(tab.id);
  } catch (error) {
    console.debug('Content script注入跳过:', tab.url, error?.message || error);
  }
}

async function ensureAllOpenTabs() {
  try {
    const tabs = await chrome.tabs.query({});
    await Promise.all(tabs.map(ensureContentScript));
  } catch (error) {
    console.debug('已打开标签页补注入失败:', error?.message || error);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  ensureAllOpenTabs();
});

chrome.runtime.onStartup.addListener(() => {
  ensureAllOpenTabs();
});

ensureAllOpenTabs();

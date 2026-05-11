const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const contentScript = fs.readFileSync(
  path.join(__dirname, '../content/content.js'),
  'utf8',
);
const contentStyles = fs.readFileSync(
  path.join(__dirname, '../content/content.css'),
  'utf8',
);
const popupScript = fs.readFileSync(
  path.join(__dirname, '../popup/popup.js'),
  'utf8',
);
const popupStyles = fs.readFileSync(
  path.join(__dirname, '../popup/popup.css'),
  'utf8',
);
const manifest = JSON.parse(fs.readFileSync(
  path.join(__dirname, '../manifest.json'),
  'utf8',
));
const newtabHtmlPath = path.join(__dirname, '../newtab/newtab.html');
const newtabStylesPath = path.join(__dirname, '../newtab/newtab.css');
const newtabScriptPath = path.join(__dirname, '../newtab/newtab.js');

test('content script does not shadow global window in openCheckWindow', () => {
  assert.doesNotMatch(contentScript, /const\s+window\s*=\s*document\.createElement/);
});

test('content stream check has an in-flight request guard', () => {
  assert.match(contentScript, /_aiCheckActiveRequest/);
  assert.match(contentScript, /AbortController/);
  assert.match(contentScript, /signal:\s*requestController\.signal/);
  assert.match(contentScript, /已有核查任务正在进行/);
});

test('floating entry is kept visible without requiring text selection', () => {
  assert.match(contentScript, /function ensurePersistentControls/);
  assert.match(contentScript, /document\.getElementById\('ai-check-float-btn'\)/);
  assert.match(contentScript, /setInterval\(ensurePersistentControls/);
  assert.match(contentScript, /window\.addEventListener\('pageshow', ensurePersistentControls/);
  assert.match(contentScript, /window\.addEventListener\('focus', ensurePersistentControls/);
  assert.doesNotMatch(contentScript, /selectedText[\s\S]{0,120}createFloatingButton/);
});

test('default browser new tab is replaced with an extension page that shows the check entry', () => {
  assert.equal(manifest.chrome_url_overrides?.newtab, 'newtab/newtab.html');
  assert.ok(fs.existsSync(newtabHtmlPath));
  assert.ok(fs.existsSync(newtabStylesPath));
  assert.ok(fs.existsSync(newtabScriptPath));

  const newtabHtml = fs.readFileSync(newtabHtmlPath, 'utf8');
  const newtabStyles = fs.readFileSync(newtabStylesPath, 'utf8');
  const newtabScript = fs.readFileSync(newtabScriptPath, 'utf8');

  assert.match(newtabHtml, /id="ai-check-newtab-entry"/);
  assert.match(newtabHtml, /popup\/popup\.js/);
  assert.match(newtabStyles, /position:\s*fixed/);
  assert.match(newtabScript, /claimText\.focus\(\)/);
});

test('popup check button has an in-flight request guard', () => {
  assert.match(popupScript, /popupCheckRunning/);
  assert.match(popupScript, /if \(popupCheckRunning\) return/);
});

test('claim text can be edited before starting a check', () => {
  assert.match(popupScript, /claimText\.addEventListener\('input'/);
  assert.match(popupScript, /function setClaimText/);
  assert.match(popupScript, /claimText\.value = currentClaim/);
  assert.match(popupStyles, /\.claim-text:focus/);
  assert.match(contentScript, /id="aiCheckClaimInput"/);
  assert.match(contentScript, /function getCurrentModalClaim/);
  assert.match(contentScript, /performCheckRealStream\(claim, false\)/);
  assert.match(contentStyles, /\.ai-check-text:focus/);
});

test('modal claim input adapts to narrow and short screens', () => {
  const containerBlock = contentStyles.match(/\.ai-check-window-container \{[\s\S]*?\n\}/)?.[0] || '';
  const bodyBlock = contentStyles.match(/\.ai-check-window-body \{[\s\S]*?\n\}/)?.[0] || '';
  const textBlock = contentStyles.match(/\.ai-check-text \{[\s\S]*?\n\}/)?.[0] || '';

  assert.match(containerBlock, /width:\s*min\(640px,\s*calc\(100vw - 32px\)\)/);
  assert.match(containerBlock, /max-height:\s*min\(88vh,\s*760px\)/);
  assert.match(bodyBlock, /padding:\s*clamp\(16px,\s*4vw,\s*28px\)/);
  assert.match(textBlock, /min-height:\s*clamp\(84px,\s*18vh,\s*140px\)/);
  assert.match(textBlock, /max-height:\s*min\(28vh,\s*220px\)/);
  assert.match(contentStyles, /@media \(max-width:\s*520px\)/);
  assert.match(contentStyles, /@media \(max-height:\s*640px\)/);
});

test('fetch network errors include the configured API base', () => {
  assert.match(contentScript, /function formatFetchError/);
  assert.match(contentScript, /无法连接核查后端/);
  assert.match(contentScript, /API_BASE/);
  assert.match(popupScript, /function formatFetchError/);
  assert.match(popupScript, /无法连接核查后端/);
  assert.match(popupScript, /API_BASE/);
});

test('yellow highlights are allowed inside full analysis reports', () => {
  assert.doesNotMatch(contentScript, /closest\('\\.reasoning-full'\)/);
  assert.doesNotMatch(contentScript, /closest\('\\.hero-summary-full'\)/);
  assert.match(contentScript, /MAX_HIGHLIGHTS_IN_FULL_REPORT\s*=\s*160/);
  assert.match(contentScript, /MAX_HIGHLIGHTS_PER_FULL_REPORT_BLOCK\s*=\s*10/);
});

test('collapsed checks show a visible completion notice in history', () => {
  assert.match(contentScript, /function showSidebarCompletionNotice/);
  assert.match(contentScript, /function completeSidebarCheck/);
  assert.match(contentScript, /function clearSidebarProgressTimer/);
  assert.match(contentScript, /sidebar-progress-item-done/);
  assert.match(contentScript, /sidebar-completion-banner/);
  assert.match(contentScript, /查看完整报告/);
  assert.match(contentScript, /核查完成<\/strong> 结果已生成/);
  assert.match(contentStyles, /completionBorderGlow/);
  assert.match(contentStyles, /completionDotPulse/);
});

test('completion notice uses restrained blue-gray treatment', () => {
  const doneCardBlock = contentStyles.match(/\.sidebar-progress-item-done \{[\s\S]*?\n\}/)?.[0] || '';
  const doneBannerBlock = contentStyles.match(/\.sidebar-completion-banner \{[\s\S]*?\n\}/)?.[0] || '';
  const doneOpenBlock = contentStyles.match(/\.sidebar-progress-open-done \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(doneCardBlock, /#f6f9fd/);
  assert.match(doneCardBlock, /#b8c6d8/);
  assert.match(doneBannerBlock, /#233b59/);
  assert.match(doneBannerBlock, /#2458a6/);
  assert.match(doneOpenBlock, /background:\s*#2458a6/);
});

test('sidebar completion stops stale progress updates', () => {
  assert.match(contentScript, /window\._aiCheckSidebarDone = true/);
  assert.ok(contentScript.includes("if (window._aiCheckSidebarDone || document.querySelector('.sidebar-progress-item-done'))"));
  assert.match(contentScript, /completeSidebarCheck\(text, finalResult\)/);
  const completionBlock = contentScript.match(/function completeSidebarCheck\(claim, resultData\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.doesNotMatch(completionBlock, /setTimeout\(\(\) => \{\s*removeSidebarMiniProgress/);
});

test('completed result collapse does not reopen running progress', () => {
  assert.match(contentScript, /function collapseCompletedResultToSidebar/);
  assert.match(contentScript, /const hasCompletedResult = currentCheckResult && resultEl && !resultEl\.classList\.contains\('hidden'\)/);
  assert.match(contentScript, /collapseCompletedResultToSidebar\(claim, currentCheckResult\)/);
  assert.match(contentScript, /window\._aiCheckSetProgress = null/);
});

test('AI summary detail uses unified markdown layout', () => {
  assert.match(contentScript, /function normalizeAISummaryMarkdown/);
  assert.match(contentScript, /summaryDetailMarkdown = normalizeAISummaryMarkdown\(summaryFull\)/);
  assert.match(contentScript, /renderLazyMarkdownDetail\(fullEl,\s*summaryDetailMarkdown\)/);
  assert.match(contentStyles, /hero-summary-full \.markdown-content \.md-h2/);
  assert.match(contentStyles, /hero-summary-full \.markdown-content \.md-p/);
  assert.match(contentStyles, /hero-summary-full \.markdown-content \.md-li/);
  assert.match(contentStyles, /hero-summary-full > \.markdown-content/);
});

test('full summary and reasoning details are rendered only after expand click', () => {
  assert.match(contentScript, /function renderLazyMarkdownDetail/);
  assert.match(contentScript, /fullEl\.dataset\.rendered = 'true'/);
  assert.match(contentScript, /let summaryDetailMarkdown = ''/);
  assert.match(contentScript, /let reasoningDetailMarkdown = ''/);
  assert.match(contentScript, /renderLazyMarkdownDetail\(fullEl,\s*summaryDetailMarkdown\)/);
  assert.match(contentScript, /renderLazyMarkdownDetail\(fullEl,\s*reasoningDetailMarkdown\)/);
  assert.doesNotMatch(contentScript, /<div class="hero-summary-full markdown-content" id="heroSummaryFull" style="display:none">\s*\$\{summaryDetailHtml\}/);
  assert.doesNotMatch(contentScript, /<div class="reasoning-full markdown-content" id="reasoningFull" style="display:none">\s*\$\{parseMarkdown\(reasoningDisplayContent\)\}/);
  assert.match(popupScript, /function renderLazyMarkdownDetail/);
  assert.match(popupScript, /let summaryDetailMarkdown = ''/);
  assert.match(popupScript, /let reasoningDetailMarkdown = ''/);
  assert.match(popupScript, /renderLazyMarkdownDetail\(fullEl,\s*summaryDetailMarkdown\)/);
  assert.match(popupScript, /renderLazyMarkdownDetail\(fullEl,\s*reasoningDetailMarkdown\)/);
});

test('live draft output is visually demoted before the final report', () => {
  assert.match(contentScript, /streaming-card streaming-card--draft/);
  assert.match(contentScript, /生成中 · 草稿分析/);
  assert.match(contentScript, /最终以正式报告为准/);
  assert.match(contentScript, /function scrollStreamingDraftToBottom/);
  assert.match(contentScript, /requestAnimationFrame/);
  assert.match(contentScript, /streaming-card-scroll-anchor/);
  const scrollBlock = contentScript.match(/function scrollStreamingDraftToBottom\(container\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(scrollBlock, /body\.scrollTop = body\.scrollHeight/);
  assert.doesNotMatch(scrollBlock, /container\.scrollTop/);
  assert.doesNotMatch(scrollBlock, /scrollIntoView/);

  const draftCardBlock = contentStyles.match(/\.streaming-card--draft \{[\s\S]*?\n\}/)?.[0] || '';
  const draftHeaderBlock = contentStyles.match(/\.streaming-card--draft \.streaming-card-header \{[\s\S]*?\n\}/)?.[0] || '';
  const draftBodyBlock = contentStyles.match(/\.streaming-card--draft \.streaming-card-body \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(draftCardBlock, /border:\s*1px dashed #cbd6e2/);
  assert.match(draftHeaderBlock, /font-size:\s*13px/);
  assert.match(draftBodyBlock, /font-size:\s*13px/);
  assert.match(draftBodyBlock, /color:\s*#6b7280/);
  assert.match(draftBodyBlock, /max-height:\s*220px/);
});

test('new history badge does not reuse verdict green', () => {
  const newBadgeBlock = contentStyles.match(/\.history-item-new-badge \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(newBadgeBlock, /background:\s*#eef3f8/);
  assert.match(newBadgeBlock, /color:\s*#34506b/);
  assert.doesNotMatch(newBadgeBlock, /#137333|#34a853|linear-gradient/);
});

test('yellow highlights skip titles and panel headings', () => {
  assert.ok(contentScript.includes("closest('h1, h2, h3, h4, h5, h6')"));
  assert.ok(contentScript.includes("closest('.md-h2, .md-h3, .md-h4')"));
  assert.ok(contentScript.includes("closest('.analysis-panel-title, .analysis-panel-kicker')"));
});

test('yellow highlights skip evidence titles and source metadata but still scan summaries', () => {
  assert.ok(contentScript.includes("closest('.evidence-title')"));
  assert.ok(contentScript.includes("closest('.evidence-source')"));
  assert.ok(!contentScript.includes("closest('.evidence-analysis')"));
});

test('keyword highlights use marker-style emphasis instead of boxed chips', () => {
  const keywordBlock = contentStyles.match(/\.kw-highlight \{[\s\S]*?\n\}/)?.[0] || '';
  const contentEvidenceBlock = contentStyles.match(/\.evidence-highlight \{[\s\S]*?\n\}/)?.[0] || '';
  const popupEvidenceBlock = popupStyles.match(/\.evidence-highlight \{[\s\S]*?\n\}/)?.[0] || '';

  assert.match(keywordBlock, /linear-gradient/);
  assert.match(keywordBlock, /text-decoration/);
  assert.doesNotMatch(keywordBlock, /border:\s*1px/);
  assert.doesNotMatch(contentEvidenceBlock, /border-radius:\s*4px/);
  assert.doesNotMatch(popupEvidenceBlock, /border-radius:\s*4px/);
});

test('evidence overview merges retrieval and quality summaries into one card', () => {
  assert.match(contentScript, /function buildEvidenceOverviewHtml/);
  assert.match(contentScript, /function stripEvidenceCountLead/);
  assert.doesNotMatch(contentScript, /class="evidence-quality-info"/);
  assert.match(popupScript, /function buildPopupEvidenceOverviewHtml/);
  assert.match(popupScript, /function stripPopupEvidenceCountLead/);
});

test('history allows repeated claims as separate records', () => {
  const saveHistoryBlock = contentScript.match(/function saveToHistory\(claim, result\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.doesNotMatch(saveHistoryBlock, /findIndex\(i => i\.claim === claim\)/);
  assert.doesNotMatch(saveHistoryBlock, /splice\(existingIdx,\s*1\)/);
  assert.match(saveHistoryBlock, /items\.unshift\(historyItem\)/);
});

test('history save handles storage quota pressure explicitly', () => {
  assert.match(contentScript, /function pruneHistoryForStorage/);
  assert.match(contentScript, /chrome\.runtime\?\.lastError/);
  assert.match(contentScript, /factcheck_history:\s*prunedItems/);
});

test('collapsing a reopened history result does not create another history item', () => {
  const saveHistoryBlock = contentScript.match(/function saveToHistory\(claim, result\) \{[\s\S]*?\n\}/)?.[0] || '';
  assert.match(saveHistoryBlock, /result\.__historySaved = true/);
  assert.match(saveHistoryBlock, /result\.__historyId = id/);

  const openHistoryBlock = contentScript.match(/function openHistoryDetail\(historyId\) \{[\s\S]*?function deleteHistoryItem/)?.[0] || '';
  assert.match(openHistoryBlock, /item\.result\.__historySaved = true/);
  assert.match(openHistoryBlock, /item\.result\.__historyId = item\.id/);
});

test('extractHighlightKeywords prioritizes claim-critical facts', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const keywords = sandbox.extractHighlightKeywords(
    '网红白冰在2021年至2024年间偷逃税款911.18万元，被处罚款1891.24万元',
    { evidence_chain: { supporting_evidence: [], opposing_evidence: [], neutral_evidence: [] } },
  );

  assert.ok(keywords.indexOf('911.18万元') > -1);
  assert.ok(keywords.indexOf('1891.24万元') > -1);
  assert.ok(keywords.indexOf('2021年至2024年') > -1);
  assert.ok(keywords.indexOf('白冰') > -1);
  assert.ok(keywords.some((kw) => kw.includes('偷逃税款')));
  assert.ok(keywords.indexOf('网红白冰在2021年至2024年间偷逃税款911') === -1);
  assert.ok(keywords.indexOf('万元') === -1);
});

test('extractHighlightKeywords includes important facts that only appear in the full report', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const keywords = sandbox.extractHighlightKeywords(
    '白冰偷税是真的吗',
    { evidence_chain: { supporting_evidence: [], opposing_evidence: [], neutral_evidence: [] } },
    '国家税务总局通报显示，白冰通过转换收入性质、虚假申报等方式少缴税款911.18万元，已被依法查处并处罚款1891.24万元。',
  );

  assert.ok(keywords.indexOf('国家税务总局') > -1);
  assert.ok(keywords.indexOf('虚假申报') > -1);
  assert.ok(keywords.indexOf('911.18万元') > -1);
  assert.ok(keywords.indexOf('1891.24万元') > -1);
});

test('extractHighlightKeywords keeps full standard and inspection phrase', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const keywords = sandbox.extractHighlightKeywords(
    '央视曝光电动车续航神器',
    { evidence_chain: { supporting_evidence: [], opposing_evidence: [], neutral_evidence: [] } },
    '电动自行车整车以外的外接设备，尚未出台统一的生产标准和检测规范。',
  );

  assert.ok(keywords.indexOf('出台统一的生产标准和检测规范') > -1);
});

test('extractHighlightKeywords avoids clipped Chinese fragments around 被 and 因', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const keywords = sandbox.extractHighlightKeywords(
    '黄子佼持有未成年性影像判决',
    { evidence_chain: { supporting_evidence: [], opposing_evidence: [], neutral_evidence: [] } },
    [
      '终审结果确定：最高法院于2026年5月7日驳回检方上诉，案件定谳。',
      '最终判决内容：黄子佼最终被判有期徒刑1年6个月，缓刑4年，无需入狱服刑。',
      '关键量刑情节：二审改判部分原因系认定黄子佼违反《个人资料保护法》，且其与37名被害人和解。',
      '案件性质：黄子佼因下载并持有2259部未成年性影像被起诉。',
    ].join('\n'),
  );

  assert.ok(keywords.indexOf('黄子佼') > -1);
  assert.ok(keywords.indexOf('未成年性影像') > -1);
  assert.ok(keywords.indexOf('有期徒刑1年6个月') > -1);
  assert.ok(keywords.indexOf('缓刑4年') > -1);
  assert.equal(keywords.indexOf('子佼最终'), -1);
  assert.equal(keywords.indexOf('判部分原'), -1);
  assert.equal(keywords.indexOf('年性影像'), -1);
});

test('extractHighlightKeywords keeps person descriptors and legal detail terms intact', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const keywords = sandbox.extractHighlightKeywords(
    '台湾艺人黄子佼收藏2259部未成年青少年性影像视频，一审遭判刑8月，二审改判缓刑4年，三审驳回上诉，案件包含姓名学校个人资料，黄子佼获缓刑定谳不需入狱服刑',
    { evidence_chain: { supporting_evidence: [], opposing_evidence: [], neutral_evidence: [] } },
    '搜狐娱乐讯 据台媒,艺人黄子佼收藏2259部未成年青少年性影像视频,一审遭判刑8月,二审虽然改判有期徒刑1年6月,但宣告缓刑4年。案经检方上诉第三审,最高法院7日驳回检方上诉,全案确定。黄子佼获得缓刑定谳,不需入狱服刑。不过因部分影像中,有女童、少女手持包含姓名、学校的个人资料拍摄。黄子佼改口认罪,并积极与被害人洽谈和解。',
  );

  assert.ok(keywords.indexOf('台湾艺人黄子佼') > -1);
  assert.ok(keywords.indexOf('艺人黄子佼') > -1);
  assert.ok(keywords.indexOf('未成年青少年性影像') > -1);
  assert.ok(keywords.indexOf('一审') > -1);
  assert.ok(keywords.indexOf('二审') > -1);
  assert.ok(keywords.indexOf('第三审') > -1);
  assert.ok(keywords.indexOf('缓刑4年') > -1);
  assert.ok(keywords.indexOf('检方上诉') > -1);
  assert.ok(keywords.indexOf('驳回检方上诉') > -1);
  assert.ok(keywords.indexOf('全案确定') > -1);
  assert.ok(keywords.indexOf('缓刑定谳') > -1);
  assert.ok(keywords.indexOf('不需入狱服刑') > -1);
  assert.ok(keywords.indexOf('包含姓名、学校的个人资料') > -1);
  assert.ok(keywords.indexOf('个人资料拍摄') > -1);
  assert.ok(keywords.indexOf('改口认罪') > -1);
  assert.ok(keywords.indexOf('被害人洽谈和解') > -1);
  assert.equal(keywords.indexOf('并积极与'), -1);
});

test('AI summary highlights keep spaced Chinese fact phrases intact', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const summary = '黄子佼因持有大量未成年 性影像终审获缓刑的说法属实。';
  const keywords = sandbox.extractHighlightKeywords(
    '黄子佼因持有大量未成年性影像终审获缓刑的说法属实',
    { evidence_chain: { supporting_evidence: [], opposing_evidence: [], neutral_evidence: [], ai_summary: { brief: summary } } },
    summary,
  );
  const matches = sandbox.findKeywordMatches(summary, '大量未成年性影像');

  assert.ok(keywords.indexOf('大量未成年性影像') > -1);
  assert.ok(keywords.indexOf('未成年性影像') > -1);
  assert.deepEqual(JSON.parse(JSON.stringify(matches)), [{ start: 6, end: 15 }]);
  assert.equal(summary.slice(matches[0].start, matches[0].end), '大量未成年 性影像');
});

test('reasoning brief prepends actual core evidence count and stance context', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const reasoning = [
    '### 3. 证据关系分析',
    '相互印证关系：证据1和证据2共同证实了湖南广电存在AI播新闻的现象。',
    '信息补充/限定关系：证据5对“AI主播正式上岗”进行了关键限定。',
  ].join('\n');

  const brief = sandbox.buildReasoningBrief(reasoning, {
    supporting_evidence: Array.from({ length: 7 }, () => ({})),
    opposing_evidence: [],
    neutral_evidence: Array.from({ length: 3 }, () => ({})),
  });

  assert.match(brief, /^10条核心证据整体指向同一结论，其中部分证据提供限定或背景。/);
  assert.match(brief, /相互印证关系/);
});

test('reasoning display filters redundant per-evidence stance section', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const reasoning = [
    '### 1. 证据立场分析',
    '**证据 1 [报道A](https://example.com/a)** - 来源：**媒体A** - **立场**：**支持** - 分析：这条证据支持说法。',
    '### 2. 综合判断',
    '整体看，核心事实成立。',
    '### 3. 证据关系分析',
    '相互印证关系：证据之间存在交叉印证。',
    '### 4. 不确定性与局限',
    '仍需注意来源发布时间。',
    '### 5. 建议',
    '继续核查。'
  ].join('\n');

  const display = sandbox.buildReasoningDisplayContent(reasoning);

  assert.doesNotMatch(display, /证据立场分析/);
  assert.doesNotMatch(display, /这条证据支持说法/);
  assert.doesNotMatch(display, /继续核查/);
  assert.doesNotMatch(display, /###\s*2[.．、]\s*综合判断/);
  assert.doesNotMatch(display, /###\s*3[.．、]\s*证据关系分析/);
  assert.match(display, /### 综合判断/);
  assert.match(display, /### 证据关系分析/);
  assert.match(display, /### 不确定性与局限/);
});

test('evidence cards show source summary instead of model analysis', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    URL,
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const html = sandbox.createEvidenceCardHTML({
    url: 'https://news.hsw.cn/example',
    title: '敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应',
    domain: 'news.hsw.cn',
    content: {
      summary: '游客在鸣沙山山顶购买到2元矿泉水，景区运营方回应称该价格长期执行。',
      analysis: '报道明确指出鸣沙山山顶的“敦煌水局”矿泉水售价为2元一瓶，直接证实了说法。',
    },
  }, 'support');

  assert.match(html, /内容摘要/);
  assert.match(html, /游客在鸣沙山山顶购买到2元矿泉水/);
  assert.doesNotMatch(html, /证据分析/);
  assert.doesNotMatch(html, /直接证实了说法/);
});

test('evidence cards leave summaries available for yellow keyword highlighting', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    URL,
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const summary = '最高法院7日驳回检方上诉，全案确定。黄子佼获得缓刑定谳，不需入狱服刑。';
  const html = sandbox.createEvidenceCardHTML({
    url: 'https://example.com/a',
    title: '黄子佼收藏2259部未成年性影像视频',
    domain: 'example.com',
    content: { summary },
  }, 'support');

  assert.match(html, /<div class="evidence-analysis">最高法院7日驳回检方上诉/);
  assert.doesNotMatch(html, /evidence-highlight/);
  assert.doesNotMatch(html, /kw-highlight/);
});

test('evidence cards expose stable anchors and reasoning mentions link to them', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    URL,
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const cardHtml = sandbox.createEvidenceCardHTML({
    url: 'https://example.com/a',
    title: '报道A',
    content: { summary: '第一条证据摘要' },
  }, 'support', 0, 3);
  const reasoningHtml = sandbox.parseMarkdown('证据1和证据 2共同印证，证据[3]提供限定，证据4-5仍需核对。');

  assert.match(cardHtml, /id="evidence-3"/);
  assert.match(cardHtml, /data-evidence-index="3"/);
  assert.match(cardHtml, /<span class="evidence-index">证据 3<\/span>/);
  assert.match(reasoningHtml, /href="#evidence-1" class="evidence-anchor-link"/);
  assert.match(reasoningHtml, /href="#evidence-2" class="evidence-anchor-link"/);
  assert.match(reasoningHtml, /href="#evidence-3" class="evidence-anchor-link"/);
  assert.match(reasoningHtml, /href="#evidence-4" class="evidence-anchor-link"/);
  assert.match(reasoningHtml, /href="#evidence-5" class="evidence-anchor-link"/);
});

test('relation styling treats negated conflicts with consistency wording as support', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    URL,
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const html = sandbox.parseMarkdown('展示的9条核心证据中，多数形成了高度一致的证据链，在核心事实上完全吻合，无任何矛盾。');

  assert.match(html, /md-relation-support/);
  assert.doesNotMatch(html, /md-relation-conflict/);
});

test('relation styling treats no major conflict wording as support', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    URL,
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const html = sandbox.parseMarkdown('多数内容高度一致，信息细节无重大矛盾，共同形成了一个密实且可靠的证据链。');

  assert.match(html, /md-relation-support/);
  assert.doesNotMatch(html, /md-relation-conflict/);
});


test('streaming markdown links are not re-linkified inside href attributes', () => {
  const sandbox = {
    EXT_CONFIG: { API_BASE: 'http://127.0.0.1:8000' },
    console: { log() {}, warn() {}, error() {} },
    document: {
      readyState: 'loading',
      addEventListener() {},
      getElementById() { return null; },
      createElement() { return { style: {}, addEventListener() {}, appendChild() {}, remove() {} }; },
      createTreeWalker() { return { nextNode() { return null; } }; },
      body: { appendChild() {} },
      title: '',
      querySelector() { return null; },
    },
    chrome: { runtime: { onMessage: { addListener() {} } }, storage: { local: {} } },
    NodeFilter: { SHOW_TEXT: 4, FILTER_REJECT: 2, FILTER_ACCEPT: 1 },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (fn) => fn(),
    URL,
    window: {},
    globalThis: {},
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(contentScript, sandbox);

  const html = sandbox.simpleMarkdownRender('证据：[官方通报](https://www.chinatax.gov.cn/example?id=1)');

  assert.match(html, /<a href="https:\/\/www\.chinatax\.gov\.cn\/example\?id=1" target="_blank" rel="noopener noreferrer" style="color:#1a73e8;">官方通报<\/a>/);
  assert.doesNotMatch(html, /href="<a href=/);
  assert.doesNotMatch(html, />[^<]*target=/);
});

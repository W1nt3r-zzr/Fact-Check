// ==================== Popup Script ====================
const API_BASE = EXT_CONFIG.API_BASE;
let currentClaim = '';
let popupCheckRunning = false;

const $ = id => document.getElementById(id);

const CONTENT_SCRIPT_FILES = [
  'config.js',
  'utils/dom.js',
  'utils/markdown.js',
  'utils/highlight.js',
  'content/content.js'
];

const CONTENT_CSS_FILES = ['content/content.css'];
const CLAIM_PLACEHOLDER = '请在网页上选中要核查的文字，或直接输入要核查的内容...';

function canInjectIntoUrl(url = '') {
  return /^(https?|file):\/\//.test(url);
}

async function ensureContentScript(tab) {
  if (!tab?.id || !canInjectIntoUrl(tab.url)) return false;

  try {
    const response = await chrome.tabs.sendMessage(tab.id, { action: 'ping' });
    if (response && response.ok) return true;
  } catch (e) {
    // No live receiver after extension reload; inject below.
  }

  try {
    await chrome.scripting.insertCSS({
      target: { tabId: tab.id },
      files: CONTENT_CSS_FILES
    });
  } catch (e) {
    console.debug('CSS注入跳过:', e?.message || e);
  }

  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: CONTENT_SCRIPT_FILES
    });
    return true;
  } catch (e) {
    console.debug('Content script注入失败:', e?.message || e);
    return false;
  }
}

async function getApiErrorMessage(response) {
  try {
    const data = await response.clone().json();
    return data.detail || data.message || `API请求失败: ${response.status}`;
  } catch (e) {
    try {
      const text = await response.text();
      return text || `API请求失败: ${response.status}`;
    } catch (innerError) {
      return `API请求失败: ${response.status}`;
    }
  }
}

function formatFetchError(error) {
  const message = error?.message || String(error || '');
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return `无法连接核查后端：${API_BASE}。请确认后端服务可访问、网络未阻断，并检查扩展已重新加载。`;
  }
  if (/abort/i.test(message)) {
    return '核查请求已取消';
  }
  return message || '核查失败，请检查后端服务';
}

document.addEventListener('DOMContentLoaded', async () => {
  const claimText = $('claimText');
  const checkBtn = $('checkBtn');
  const clearBtn = $('clearBtn');
  const footerText = document.querySelector('.footer-text');

  claimText.placeholder = CLAIM_PLACEHOLDER;
  if (footerText && EXT_CONFIG.VERSION) {
    footerText.textContent = `由 DeepSeek 驱动 · v${EXT_CONFIG.VERSION}`;
  }
  checkForExtensionUpdate();

  // Load saved text
  chrome.storage.local.get(['lastSelectedText'], (result) => {
    if (result && result.lastSelectedText) {
      setClaimText(result.lastSelectedText);
      chrome.storage.local.remove(['lastSelectedText']);
    } else {
      getSelectedText();
    }
  });

  claimText.addEventListener('input', () => {
    setClaimText(claimText.value, { preserveDomValue: true });
  });
  checkBtn.addEventListener('click', handleCheck);
  clearBtn.addEventListener('click', handleClear);
});

async function checkForExtensionUpdate() {
  if (typeof fetchLatestReleaseStatus !== 'function') return;
  if (EXT_CONFIG.UPDATE_CHECK?.enabled === false) return;

  try {
    const status = await fetchLatestReleaseStatus(EXT_CONFIG);
    if (status.hasUpdate) {
      renderUpdateNotice(status);
    }
  } catch (error) {
    console.debug('检查插件更新失败:', error?.message || error);
  }
}

function renderUpdateNotice(status) {
  const notice = $('updateNotice');
  if (!notice) return;

  const downloadUrl = status.downloadUrl || status.releaseUrl;
  const latestVersion = escapeHtml(status.latestVersion || '');
  const currentVersion = escapeHtml(status.currentVersion || EXT_CONFIG.VERSION || '');

  notice.innerHTML = `
    <div class="update-copy">
      <div class="update-title">发现新版本 v${latestVersion}</div>
      <div class="update-meta">当前版本 v${currentVersion}，下载后在扩展管理页重新加载插件即可更新。</div>
    </div>
    ${downloadUrl ? `<a class="update-link" href="${escapeHtml(downloadUrl)}" target="_blank" rel="noopener noreferrer">下载最新版</a>` : ''}
  `;
  notice.classList.remove('hidden');
}

function setClaimText(value, options = {}) {
  currentClaim = String(value || '').trim();
  const claimText = $('claimText');
  if (claimText && !options.preserveDomValue) {
    claimText.value = currentClaim;
  }
  if (claimText) {
    claimText.classList.toggle('empty', !currentClaim);
  }
  const checkBtn = $('checkBtn');
  if (checkBtn) checkBtn.disabled = !currentClaim;
}

async function getSelectedText() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return;
    const ready = await ensureContentScript(tab);
    if (!ready) return;

    chrome.tabs.sendMessage(tab.id, { action: 'getSelection' }, (response) => {
      if (chrome.runtime.lastError) return;
      if (response && response.text) {
        setClaimText(response.text);
      }
    });
  } catch (e) {
    console.error('获取选中文字失败:', e);
  }
}

async function handleCheck() {
  if (!currentClaim) return;
  if (popupCheckRunning) return;

  popupCheckRunning = true;
  $('checkBtn').disabled = true;
  $('resultArea').classList.add('hidden');
  $('errorArea').classList.add('hidden');

  const progressArea = $('progressArea');
  const progressFill = $('progressFill');
  const progressText = $('progressText');
  progressArea.classList.remove('hidden');
  progressFill.style.width = '10%';
  progressText.textContent = '正在联网搜索证据...';

  const startTime = Date.now();
  const timer = setInterval(() => {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    progressText.textContent = `正在核查中...（已用${formatTime(elapsed)}）`;
  }, 1000);

  try {
    progressFill.style.width = '30%';
    progressText.textContent = '正在调用AI推理...';

    const response = await fetch(`${API_BASE}/api/v1/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ claim: currentClaim, enable_thinking: false, enable_evidence_chain: true })
    });

    if (!response.ok) throw new Error(await getApiErrorMessage(response));
    const data = await response.json();

    progressFill.style.width = '100%';
    progressText.textContent = '核查完成';

    displayPopupResult(data);

  } catch (error) {
    $('errorText').textContent = formatFetchError(error);
    $('errorArea').classList.remove('hidden');
  } finally {
    clearInterval(timer);
    setTimeout(() => progressArea.classList.add('hidden'), 500);
    popupCheckRunning = false;
    $('checkBtn').disabled = false;
  }
}

function displayPopupResult(data) {
  let html = '';
  let summaryDetailMarkdown = '';
  let reasoningDetailMarkdown = '';

  // Hero AI Summary
  if (data.evidence_chain && data.evidence_chain.ai_summary) {
    const summary = data.evidence_chain.ai_summary;
    const brief = summary.brief || 'AI归纳总结';
    let full = summary.full || '';
    const evidenceCount = data.evidence_chain.total_evidence ||
      ((data.evidence_chain.supporting_evidence?.length || 0) +
       (data.evidence_chain.opposing_evidence?.length || 0) +
       (data.evidence_chain.neutral_evidence?.length || 0));
    const summaryMeta = evidenceCount > 0 ? `基于 ${evidenceCount} 条核心证据` : '综合证据分析';
    // 去除开头摘要部分，避免重复
    if (full && brief && full.startsWith(brief)) {
      full = full.substring(brief.length).trim().replace(/^[\n\r\s，,。.、]+/, '');
    }
    summaryDetailMarkdown = full;
    html += `<div class="analysis-panel hero-summary">
      <div class="analysis-panel-header">
        <div>
          <div class="analysis-panel-kicker">AI归纳总结</div>
          <div class="analysis-panel-title">关键结论</div>
        </div>
        <span class="analysis-panel-meta">${summaryMeta}</span>
      </div>
      <div class="hero-summary-brief analysis-brief">${escapeHtml(brief)}</div>
      ${full && full.length > 10 ? `
        <button class="hero-expand-btn analysis-expand-btn" id="heroSummaryExpand">展开详细分析 ▼</button>
        <div class="hero-summary-full markdown-content" id="heroSummaryFull" style="display:none"></div>
      ` : ''}
    </div>`;
  }

  // Tab data
  const ec = data.evidence_chain;
  const items = ec?.items || [];
  const support = items.length ? items.filter(i => i.stance === 'support') : (ec?.supporting_evidence || []);
  const oppose = items.length ? items.filter(i => i.stance === 'oppose') : (ec?.opposing_evidence || []);
  const neutral = items.length ? items.filter(i => i.stance === 'neutral') : (ec?.neutral_evidence || []);
  const totalEvidence = items.length;

  // 从 supporting/opposing/neutral evidence 计算总数（兼容两种数据格式）
  const actualTotal = totalEvidence > 0 ? totalEvidence :
    (ec?.supporting_evidence?.length || 0) + (ec?.opposing_evidence?.length || 0) + (ec?.neutral_evidence?.length || 0);

  let reasoningBrief = '';
  if (data.reasoning) reasoningBrief = buildPopupReasoningBrief(data.reasoning, ec);

  // Tab bar
  html += `
    <div class="tab-bar">
      <button class="tab-item tab-active" data-tab="evidence">证据链 (${actualTotal})</button>
      <button class="tab-item" data-tab="reasoning">证据解读</button>
    </div>
  `;

  // Evidence tab
  html += `<div class="tab-content" id="tab-evidence">`;
  if (actualTotal > 0) {
    // 证据检索逻辑说明
    const totalSearchResults = ec?.total_search_results || 0;
    html += buildPopupEvidenceOverviewHtml(totalSearchResults, actualTotal, ec?.reasoning_summary);

    html += `
      <div class="stats-row">
        <div class="stat-card stat-support"><span class="stat-num">${support.length}</span><span class="stat-label">支持</span></div>
        <div class="stat-card stat-oppose"><span class="stat-num">${oppose.length}</span><span class="stat-label">反对</span></div>
        <div class="stat-card stat-neutral"><span class="stat-num">${neutral.length}</span><span class="stat-label">中性</span></div>
      </div>
    `;
    if (support.length > 0) {
      html += `<section class="evidence-section evidence-section-support">
        <div class="evidence-group-title">✅ 支持性证据</div>`;
      support.forEach(e => html += renderCard(e, 'support'));
      html += `</section>`;
    }
    if (oppose.length > 0) {
      html += `<section class="evidence-section evidence-section-oppose">
        <div class="evidence-group-title">❌ 反对性证据</div>`;
      oppose.forEach(e => html += renderCard(e, 'oppose'));
      html += `</section>`;
    }
    if (neutral.length > 0) {
      html += `<section class="evidence-section evidence-section-neutral">
        <div class="evidence-group-title">⚪ 中性证据</div>`;
      neutral.forEach(e => html += renderCard(e, 'neutral'));
      html += `</section>`;
    }
  } else {
    html += `<div class="tab-empty">暂无证据数据</div>`;
  }
  html += `</div>`;

  // Reasoning tab
  html += `<div class="tab-content" id="tab-reasoning" style="display:none">`;
  if (data.reasoning) {
    const reasoningDisplayContent = buildPopupReasoningDisplayContent(data.reasoning);
    reasoningDetailMarkdown = reasoningDisplayContent;
    html += `
      <div class="reasoning-panel">
        <div class="analysis-panel-header">
          <div>
            <div class="analysis-panel-kicker">证据解读</div>
            <div class="analysis-panel-title">引用、关系与局限</div>
          </div>
          <span class="analysis-panel-meta">可展开审阅</span>
        </div>
        <div class="reasoning-brief">${escapeHtml(reasoningBrief)}</div>
        <button class="hero-expand-btn analysis-expand-btn" id="reasoningExpand">展开引用、关系与局限 ▼</button>
        <div class="reasoning-full markdown-content" id="reasoningFull" style="display:none"></div>
      </div>
    `;
  } else {
    html += `<div class="tab-empty">暂无证据解读</div>`;
  }
  html += `</div>`;

  $('resultArea').innerHTML = html;
  $('resultArea').classList.remove('hidden');

  // Hero expand
  const heroExpandBtn = document.getElementById('heroSummaryExpand');
  if (heroExpandBtn) {
    heroExpandBtn.addEventListener('click', () => {
      const fullEl = document.getElementById('heroSummaryFull');
      if (fullEl.style.display === 'none') {
        renderLazyMarkdownDetail(fullEl, summaryDetailMarkdown);
        fullEl.style.display = 'block';
        heroExpandBtn.textContent = '收起详细分析 ▲';
      } else {
        fullEl.style.display = 'none';
        heroExpandBtn.textContent = '展开详细分析 ▼';
      }
    });
  }

  // Reasoning expand
  const reasoningExpandBtn = document.getElementById('reasoningExpand');
  if (reasoningExpandBtn) {
    reasoningExpandBtn.addEventListener('click', () => {
      const fullEl = document.getElementById('reasoningFull');
      if (fullEl.style.display === 'none') {
        renderLazyMarkdownDetail(fullEl, reasoningDetailMarkdown);
        fullEl.style.display = 'block';
        reasoningExpandBtn.textContent = '收起引用、关系与局限 ▲';
      } else {
        fullEl.style.display = 'none';
        reasoningExpandBtn.textContent = '展开引用、关系与局限 ▼';
      }
    });
  }

  // Tab switching
  document.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('tab-active'));
      tab.classList.add('tab-active');
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
      const target = document.getElementById('tab-' + tab.dataset.tab);
      if (target) target.style.display = 'block';
    });
  });
}

function buildPopupEvidenceOverviewHtml(totalSearchResults, totalEvidence, reasoningSummary) {
  const lines = [];
  if (totalSearchResults > totalEvidence) {
    lines.push(`检索到 ${totalSearchResults} 个结果，其中 ${totalEvidence} 个与待核查说法匹配度较高，已作为核心证据进行分析；其余结果可能为重复转载、背景信息或相关性较弱内容。`);
  } else if (totalEvidence > 0) {
    lines.push(`已选取 ${totalEvidence} 条核心证据进行分析。`);
  }

  const qualitySummary = stripPopupEvidenceCountLead(reasoningSummary);
  if (qualitySummary) {
    lines.push(qualitySummary);
  }

  return lines.length
    ? `<div class="evidence-retrieval-info">📊 ${lines.map(line => renderInlineMarkdown(line)).join('<br>')}</div>`
    : '';
}

function stripPopupEvidenceCountLead(text) {
  return String(text || '')
    .replace(/^共检索到\d+条证据，覆盖\d+个不同域名来源。\s*/u, '')
    .trim();
}

function renderLazyMarkdownDetail(fullEl, markdown) {
  if (!fullEl || fullEl.dataset.rendered === 'true') return;
  fullEl.innerHTML = parseMarkdown(markdown || '');
  fullEl.dataset.rendered = 'true';
}

function renderCard(evidence, type) {
  const summary = evidence.content?.summary || evidence.summary || '';
  const highlights = evidence.highlights || [];
  const url = evidence.url || '';
  const domain = evidence.domain || (url ? url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0] : '');
  const publishDate = evidence.validation?.publish_date || evidence.publish_date || '';
  const focusHtml = typeof buildEvidenceFocusHtml === 'function'
    ? buildEvidenceFocusHtml(summary, highlights, { maxLength: 130, maxSnippets: 2 })
    : '';
  const summaryHtml = typeof buildEvidenceSummaryHtml === 'function'
    ? buildEvidenceSummaryHtml(summary, highlights, { maxLength: 120 })
    : `${escapeHtml(summary.substring(0, 120))}${summary.length > 120 ? '...' : ''}`;

  let sourceInfo = '';
  if (domain || publishDate) {
    const parts = [];
    if (domain) parts.push(`来源: ${escapeHtml(domain)}`);
    if (publishDate) parts.push(escapeHtml(publishDate));
    sourceInfo = `<div class="evidence-source">${parts.join(' | ')}</div>`;
  }

  const linkStatus = evidence.validation?.link_status || evidence.link_status;
  const linkHtml = url
    ? (linkStatus === '不可访问'
        ? `<span class="evidence-link evidence-link-broken" title="该链接已失效或无法访问">⚠️ 链接已失效</span>`
        : `<a href="${url}" target="_blank" class="evidence-link">查看原文 →</a>`)
    : '';

  return `<div class="evidence-card" data-type="${type}">
    <div class="evidence-title">${escapeHtml(evidence.title || '')}</div>
    ${sourceInfo}
    ${focusHtml}
    ${summary ? `<div class="evidence-summary">${summaryHtml}</div>` : ''}
    ${linkHtml}
  </div>`;
}

function handleClear() {
  setClaimText('');
  $('resultArea').classList.add('hidden');
  $('errorArea').classList.add('hidden');
}

function extractFirstParagraph(text, maxLength = 120) {
  if (!text) return '';
  const paragraphs = text.split(/\n\n+/).filter(p => p.trim());
  for (const para of paragraphs) {
    const t = para.trim().replace(/\*\*/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/^#+\s+/gm, '');
    if (t.length > 15) return t.length > maxLength ? t.substring(0, maxLength) + '...' : t;
  }
  return text.substring(0, maxLength) + '...';
}

function buildPopupEvidenceRelationLead(ec) {
  const items = ec?.items || [];
  const support = items.length ? items.filter(i => i.stance === 'support').length : (ec?.supporting_evidence || []).length;
  const oppose = items.length ? items.filter(i => i.stance === 'oppose').length : (ec?.opposing_evidence || []).length;
  const neutral = items.length ? items.filter(i => i.stance === 'neutral').length : (ec?.neutral_evidence || []).length;
  const total = ec?.total_evidence || items.length || support + oppose + neutral;
  if (!total) return '';

  if (support === total) return `所有${total}条核心证据均支持该说法。`;
  if (oppose === total) return `所有${total}条核心证据均反对该说法。`;
  if (oppose === 0 && support > 0) return `${total}条核心证据整体指向同一结论，其中部分证据提供限定或背景。`;
  if (support === 0 && oppose > 0) return `${total}条核心证据整体反对该说法，其中部分证据提供限定或背景。`;
  if (support > oppose) return `${total}条核心证据以支持为主，但存在反对或中性信息需要一并审阅。`;
  if (oppose > support) return `${total}条核心证据以反对为主，但存在支持或中性信息需要一并审阅。`;
  return `${total}条核心证据呈现多种立场，需要结合证据关系综合判断。`;
}

function buildPopupReasoningBrief(text, ec) {
  const lead = buildPopupEvidenceRelationLead(ec);
  const detail = extractFirstParagraph(text);
  if (lead && detail) return `${lead}${detail}`;
  return lead || detail || '';
}

function buildPopupReasoningDisplayContent(text) {
  if (!text) return '';

  let content = typeof normalizeMarkdownLineBreaks === 'function'
    ? normalizeMarkdownLineBreaks(text)
    : String(text).replace(/<br\s*\/?>/gi, '\n');
  content = content.replace(
    /###\s*1[\.．、\s]*.*?证据立场分析[\s\S]*?(?=\n###\s*\d+[\.．、\s]|$)/i,
    ''
  );
  content = content.replace(/###\s*5[\.．、][\s\S]*$/i, '');
  content = normalizePopupReasoningDisplayHeadings(content);
  content = content.replace(/\n{3,}/g, '\n\n').trim();

  return content || extractFirstParagraph(text, 350);
}

function normalizePopupReasoningDisplayHeadings(text) {
  if (!text) return '';

  return String(text).replace(
    /^(#{2,4})\s*\d+\s*[\.．、]\s*(关键引用|综合判断|证据关系分析|不确定性与局限|不确定性|局限|引用|证据关系|关系分析)(.*)$/gm,
    (_, hashes, title, suffix) => `${hashes} ${title}${suffix || ''}`
  );
}

function generatePopupSuggestions(data) {
  const suggestions = [];
  const ec = data.evidence_chain;
  if (!ec) return suggestions;

  const items = ec.items || [];
  const support = items.filter(i => i.stance === 'support').length;
  const oppose = items.filter(i => i.stance === 'oppose').length;
  const neutral = items.filter(i => i.stance === 'neutral').length;
  const total = items.length;

  if (total <= 2) {
    suggestions.push('证据较少，建议尝试换一种表述方式重新核查，或补充更具体的时间、地点等细节');
  }
  if (support > 0 && oppose > 0) {
    suggestions.push('存在支持与反对的证据分歧，建议关注不同信息源的角度差异，综合判断');
  }
  if (neutral >= total * 0.6) {
    suggestions.push('大部分证据为中性参考，无法直接验证或反驳该说法，建议寻找更权威的信息源');
  }

  suggestions.push('以上核查结果仅供参考，涉及重要决策时请咨询权威机构或专业渠道');
  return suggestions;
}

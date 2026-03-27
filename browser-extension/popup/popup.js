// ==================== 全局变量 ====================
const API_BASE_URL = 'http://localhost:8000';
let currentClaim = '';

// ==================== DOM元素 ====================
const elements = {
  claimText: document.getElementById('claimText'),
  checkBtn: document.getElementById('checkBtn'),
  clearBtn: document.getElementById('clearBtn'),
  loading: document.getElementById('loading'),
  resultArea: document.getElementById('resultArea'),
  errorArea: document.getElementById('errorArea'),
  // 结论相关
  verdictBadge: document.getElementById('verdictBadge'),
  verdictText: document.getElementById('verdictText'),
  confidenceInfo: document.getElementById('confidenceInfo'),
  // 推理过程
  reasoningSection: document.getElementById('reasoningSection'),
  reasoningText: document.getElementById('reasoningText'),
  // 证据链
  evidenceSection: document.getElementById('evidenceSection'),
  supportingEvidence: document.getElementById('supportingEvidence'),
  supportingList: document.getElementById('supportingList'),
  opposingEvidence: document.getElementById('opposingEvidence'),
  opposingList: document.getElementById('opposingList'),
  neutralEvidence: document.getElementById('neutralEvidence'),
  neutralList: document.getElementById('neutralList'),
  // 统计信息
  statsSection: document.getElementById('statsSection'),
  totalCount: document.getElementById('totalCount'),
  authorityCount: document.getElementById('authorityCount'),
  avgScore: document.getElementById('avgScore'),
  // 关键发现和不确定性
  findingsSection: document.getElementById('findingsSection'),
  findingsList: document.getElementById('findingsList'),
  uncertaintySection: document.getElementById('uncertaintySection'),
  uncertaintyText: document.getElementById('uncertaintyText'),
  // 错误提示
  errorText: document.getElementById('errorText')
};

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', async () => {
  console.log('✅ Popup已加载');

  // 先从storage中读取上次保存的文字
  chrome.storage.local.get(['lastSelectedText'], (result) => {
    if (result && result.lastSelectedText) {
      console.log('从storage读取到保存的文字:', result.lastSelectedText);
      currentClaim = result.lastSelectedText;
      elements.claimText.textContent = currentClaim;
      elements.claimText.classList.remove('empty');
      elements.checkBtn.disabled = false;

      // 清除storage中的文字
      chrome.storage.local.remove(['lastSelectedText']);
      return;
    }

    // 如果storage中没有，则从当前页面获取
    getSelectedText();
  });

  // 绑定事件监听器
  elements.checkBtn.addEventListener('click', handleCheck);
  elements.clearBtn.addEventListener('click', handleClear);
});

// ==================== 获取选中的文字 ====================
async function getSelectedText() {
  try {
    console.log('开始获取选中文字...');

    // 获取当前活动标签页
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    console.log('当前标签页:', tab);

    if (!tab || !tab.id) {
      console.error('无法获取当前标签页');
      showError('无法获取当前标签页信息');
      return;
    }

    // 向content script发送消息获取选中的文字
    chrome.tabs.sendMessage(tab.id, { action: 'getSelection' }, (response) => {
      console.log('收到content script响应:', response);

      if (chrome.runtime.lastError) {
        console.error('Chrome runtime错误:', chrome.runtime.lastError);
        showError('无法获取选中文字，请刷新页面后重试');
        return;
      }

      if (response && response.text) {
        currentClaim = response.text;
        elements.claimText.textContent = currentClaim;
        elements.claimText.classList.remove('empty');
        elements.checkBtn.disabled = false;
        console.log('✅ 成功获取选中文字:', currentClaim);
      } else {
        elements.claimText.textContent = '请在网页上选中要核查的文字...';
        elements.claimText.classList.add('empty');
        elements.checkBtn.disabled = true;
        console.log('⚠️ 未获取到选中文字');
      }
    });
  } catch (error) {
    console.error('❌ 获取选中文字异常:', error);
    showError('获取选中文字失败: ' + error.message);
  }
}

// ==================== 处理核查按钮点击 ====================
async function handleCheck() {
  if (!currentClaim) {
    showError('请先在网页上选中要核查的文字');
    return;
  }

  console.log('开始核查:', currentClaim);

  // 显示加载动画
  showLoading();
  hideError();
  hideResult();

  try {
    // 调用后端API
    const result = await callCheckAPI(currentClaim);
    console.log('核查结果:', result);

    // 显示结果
    displayResult(result);
  } catch (error) {
    console.error('核查失败:', error);
    showError(error.message || '核查失败，请检查后端服务是否启动');
  } finally {
    hideLoading();
  }
}

// ==================== 调用后端API ====================
async function callCheckAPI(claim) {
  const response = await fetch(`${API_BASE_URL}/api/v1/check`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      claim: claim,
      enable_thinking: true,
      enable_evidence_chain: true
    })
  });

  if (!response.ok) {
    throw new Error(`API请求失败: ${response.status}`);
  }

  return await response.json();
}

// ==================== 显示核查结果 ====================
function displayResult(data) {
  // 1. 显示结论
  displayVerdict(data.verdict, data.confidence);

  // 2. 显示推理过程（如果有）
  if (data.reasoning) {
    elements.reasoningText.textContent = data.reasoning;
    elements.reasoningSection.classList.remove('hidden');
  }

  // 3. 显示证据链（如果有）
  if (data.evidence_chain) {
    displayEvidenceChain(data.evidence_chain);
  }

  // 4. 显示统计信息（如果有证据链）
  if (data.evidence_chain) {
    displayStats(data.evidence_chain);
  }

  // 5. 显示关键发现（如果有证据链）
  if (data.evidence_chain && data.evidence_chain.key_findings) {
    displayFindings(data.evidence_chain.key_findings);
  }

  // 6. 显示不确定性说明
  if (data.uncertainty_note && data.uncertainty_note !== '无') {
    elements.uncertaintyText.textContent = data.uncertainty_note;
    elements.uncertaintySection.classList.remove('hidden');
  }

  // 显示结果区域
  elements.resultArea.classList.remove('hidden');
}

// ==================== 显示结论 ====================
function displayVerdict(verdict, confidence) {
  let badgeClass = '';
  let badgeText = '';

  // 根据结论设置样式
  if (verdict.includes('属实')) {
    badgeClass = 'true';
    badgeText = '✓ 属实';
  } else if (verdict.includes('不实')) {
    badgeClass = 'false';
    badgeText = '✗ 不实';
  } else {
    badgeClass = 'uncertain';
    badgeText = '? 信息不足';
  }

  elements.verdictBadge.className = `verdict-badge ${badgeClass}`;
  elements.verdictBadge.textContent = badgeText;
  elements.verdictText.textContent = verdict;

  // 显示置信度
  if (confidence) {
    elements.confidenceInfo.textContent = `置信度: ${confidence.toFixed(1)}%`;
  }
}

// ==================== 显示证据链 ====================
function displayEvidenceChain(chain) {
  let hasEvidence = false;

  // 显示支持性证据
  if (chain.supporting_evidence && chain.supporting_evidence.length > 0) {
    elements.supportingList.innerHTML = chain.supporting_evidence
      .map(evidence => createEvidenceCard(evidence, 'support'))
      .join('');
    elements.supportingEvidence.classList.remove('hidden');
    hasEvidence = true;
  }

  // 显示反对性证据
  if (chain.opposing_evidence && chain.opposing_evidence.length > 0) {
    elements.opposingList.innerHTML = chain.opposing_evidence
      .map(evidence => createEvidenceCard(evidence, 'oppose'))
      .join('');
    elements.opposingEvidence.classList.remove('hidden');
    hasEvidence = true;
  }

  // 显示中性证据
  if (chain.neutral_evidence && chain.neutral_evidence.length > 0) {
    elements.neutralList.innerHTML = chain.neutral_evidence
      .map(evidence => createEvidenceCard(evidence, 'neutral'))
      .join('');
    elements.neutralEvidence.classList.remove('hidden');
    hasEvidence = true;
  }

  // 如果有证据，显示证据链区域
  if (hasEvidence) {
    elements.evidenceSection.classList.remove('hidden');
  }
}

// ==================== 创建证据卡片HTML ====================
function createEvidenceCard(evidence, type) {
  const scores = evidence.scores || {};
  const tags = evidence.tags || [];
  const highlights = evidence.highlights || [];

  return `
    <div class="evidence-card">
      <div class="evidence-header">
        <span class="evidence-rank">#${evidence.rank}</span>
        <span class="evidence-tier">${evidence.tier || 'N/A'}</span>
        <span class="evidence-score">${(scores.overall || 0).toFixed(0)}分</span>
      </div>
      <div class="evidence-title">${escapeHtml(evidence.title)}</div>
      <div class="evidence-summary">${escapeHtml(evidence.content?.summary || '')}</div>
      ${tags.length > 0 ? `
        <div class="evidence-tags">
          ${tags.map(tag => {
            const tagClass = (tag === '官方' || tag === '权威') ? 'official authority' : '';
            return `<span class="tag ${tagClass}">${escapeHtml(tag)}</span>`;
          }).join('')}
        </div>
      ` : ''}
      <a href="${evidence.url}" target="_blank" class="evidence-link">查看原文 →</a>
    </div>
  `;
}

// ==================== 显示统计信息 ====================
function displayStats(chain) {
  elements.totalCount.textContent = chain.total_evidence || 0;
  elements.authorityCount.textContent = chain.authoritative_sources || 0;
  elements.avgScore.textContent = (chain.average_score || 0).toFixed(1);
  elements.statsSection.classList.remove('hidden');
}

// ==================== 显示关键发现 ====================
function displayFindings(findings) {
  if (!findings || findings.length === 0) return;

  elements.findingsList.innerHTML = findings
    .map(finding => `<li>${escapeHtml(finding)}</li>`)
    .join('');
  elements.findingsSection.classList.remove('hidden');
}

// ==================== 清空按钮处理 ====================
function handleClear() {
  currentClaim = '';
  elements.claimText.textContent = '请在网页上选中要核查的文字...';
  elements.claimText.classList.add('empty');
  elements.checkBtn.disabled = true;
  hideResult();
  hideError();
}

// ==================== 工具函数 ====================
function showLoading() {
  elements.loading.classList.remove('hidden');
}

function hideLoading() {
  elements.loading.classList.add('hidden');
}

function showResult() {
  elements.resultArea.classList.remove('hidden');
}

function hideResult() {
  elements.resultArea.classList.add('hidden');
}

function showError(message) {
  elements.errorText.textContent = message;
  elements.errorArea.classList.remove('hidden');
}

function hideError() {
  elements.errorArea.classList.add('hidden');
}

// HTML转义函数，防止XSS攻击
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

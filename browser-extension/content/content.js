// ==================== Content Script ====================
// 这个脚本会被注入到所有网页中，负责获取用户选中的文字和显示浮动按钮

console.log('✅ AI信息核查助手 Content Script 已加载');

// ==================== 创建浮动按钮 ====================
function createFloatingButton() {
  // 检查是否已存在按钮
  if (document.getElementById('ai-check-float-btn')) {
    return;
  }

  const button = document.createElement('div');
  button.id = 'ai-check-float-btn';
  button.innerHTML = '🔍';
  button.title = 'AI信息核查';

  // 设置样式
  Object.assign(button.style, {
    position: 'fixed',
    bottom: '100px',
    right: '20px',
    width: '56px',
    height: '56px',
    backgroundColor: '#1a73e8',
    color: '#ffffff',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '24px',
    cursor: 'pointer',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    zIndex: '2147483647',
    transition: 'all 0.3s ease',
    userSelect: 'none'
  });

  // 悬停效果
  button.addEventListener('mouseenter', () => {
    button.style.transform = 'scale(1.1)';
    button.style.boxShadow = '0 6px 16px rgba(0, 0, 0, 0.2)';
  });

  button.addEventListener('mouseleave', () => {
    button.style.transform = 'scale(1)';
    button.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
  });

  // 点击事件 - 直接打开核查窗口
  button.addEventListener('click', () => {
    console.log('🖱️ 浮动按钮被点击');

    const selectedText = getSelectedText();
    console.log('获取到的选中文字:', selectedText ? `"${selectedText}"` : '无');

    if (selectedText && selectedText.length > 0) {
      // 直接打开核查窗口
      openCheckWindow(selectedText);
    } else {
      // 显示提示
      console.log('⚠️ 未选中文字');
      showToast('⚠️ 请先选中要核查的文字');
    }
  });

  document.body.appendChild(button);
  console.log('✅ 浮动按钮已创建');
}

// ==================== 创建提示消息 ====================
function showToast(message) {
  console.log('📢 显示提示消息:', message);

  const toast = document.createElement('div');
  toast.id = 'ai-check-toast';
  toast.textContent = message;
  Object.assign(toast.style, {
    position: 'fixed',
    bottom: '170px',
    right: '20px',
    backgroundColor: '#323232',
    color: '#ffffff',
    padding: '12px 20px',
    borderRadius: '8px',
    fontSize: '14px',
    zIndex: '2147483647',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    animation: 'slideIn 0.3s ease',
    maxWidth: '300px',
    wordWrap: 'break-word'
  });

  document.body.appendChild(toast);
  console.log('✅ Toast已添加到页面');

  // 3秒后自动消失
  setTimeout(() => {
    console.log('⏰ 移除Toast');
    toast.style.animation = 'slideOut 0.3s ease';
    setTimeout(() => {
      toast.remove();
      console.log('✅ Toast已移除');
    }, 300);
  }, 3000);
}

// ==================== 打开核查窗口 ====================
function openCheckWindow(text) {
  console.log('🪟 打开核查窗口，文字:', text);

  // 如果窗口已存在，先关闭
  const existingWindow = document.getElementById('ai-check-window');
  if (existingWindow) {
    existingWindow.remove();
  }

  // 创建窗口容器
  const window = document.createElement('div');
  window.id = 'ai-check-window';
  window.innerHTML = `
    <div class="ai-check-window-overlay" id="aiCheckOverlay"></div>
    <div class="ai-check-window-container">
      <div class="ai-check-window-header">
        <h2>🔍 AI信息核查</h2>
        <button class="ai-check-close-btn" id="aiCheckClose">✕</button>
      </div>
      <div class="ai-check-window-body">
        <div class="ai-check-section">
          <div class="ai-check-label">待核查内容</div>
          <div class="ai-check-text">${escapeHtml(text)}</div>
        </div>
        <button class="ai-check-btn-primary" id="aiCheckStart">
          <span>⚡</span> 开始核查
        </button>
        <div id="aiCheckLoading" class="ai-check-loading hidden">
          <div class="ai-check-spinner"></div>
          <p>正在核查中...</p>
          <p class="ai-check-hint">这可能需要10-30秒</p>
        </div>
        <div id="aiCheckResult" class="ai-check-result hidden"></div>
      </div>
    </div>
  `;

  document.body.appendChild(window);

  // 绑定关闭按钮
  document.getElementById('aiCheckClose').addEventListener('click', closeCheckWindow);
  document.getElementById('aiCheckOverlay').addEventListener('click', closeCheckWindow);

  // 绑定开始核查按钮
  document.getElementById('aiCheckStart').addEventListener('click', async () => {
    console.log('开始核查:', text);
    await performCheck(text);
  });

  console.log('✅ 核查窗口已创建');
}

// ==================== 关闭核查窗口 ====================
function closeCheckWindow() {
  const window = document.getElementById('ai-check-window');
  if (window) {
    window.remove();
    console.log('✅ 核查窗口已关闭');
  }
}

// ==================== 执行核查 ====================
async function performCheck(text) {
  const loading = document.getElementById('aiCheckLoading');
  const result = document.getElementById('aiCheckResult');
  const startBtn = document.getElementById('aiCheckStart');

  // 显示加载动画
  loading.classList.remove('hidden');
  result.classList.add('hidden');
  startBtn.disabled = true;

  try {
    console.log('📡 调用API...');

    const response = await fetch('http://localhost:8000/api/v1/check', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        claim: text,
        enable_thinking: true,
        enable_evidence_chain: true
      })
    });

    if (!response.ok) {
      throw new Error(`API请求失败: ${response.status}`);
    }

    const data = await response.json();
    console.log('✅ 核查结果:', data);

    // 显示结果
    displayResult(data, text);

    // 提取并高亮关键词
    highlightKeywordsInPage(text);

  } catch (error) {
    console.error('❌ 核查失败:', error);
    showError(error.message || '核查失败，请检查后端服务是否启动');
  } finally {
    loading.classList.add('hidden');
    startBtn.disabled = false;
  }
}

// ==================== 显示核查结果 ====================
function displayResult(data, originalClaim) {
  const result = document.getElementById('aiCheckResult');
  result.classList.remove('hidden');

  console.log('📊 显示核查结果:', data);

  let html = '';

  // 结论部分
  let verdictClass = '';
  let verdictIcon = '';
  if (data.verdict.includes('属实')) {
    verdictClass = 'verdict-true';
    verdictIcon = '✓';
  } else if (data.verdict.includes('不实')) {
    verdictClass = 'verdict-false';
    verdictIcon = '✗';
  } else {
    verdictClass = 'verdict-uncertain';
    verdictIcon = '?';
  }

  html += `
    <div class="ai-check-section">
      <div class="ai-check-label">核查结论</div>
      <div class="ai-check-verdict ${verdictClass}">
        <span class="verdict-icon">${verdictIcon}</span>
        <span class="verdict-text">${data.verdict}</span>
        ${data.confidence ? `<span class="verdict-confidence">置信度: ${data.confidence.toFixed(1)}%</span>` : ''}
      </div>
    </div>
  `;

  // 推理过程（优化Markdown渲染，默认折叠，显示简短摘要）
  if (data.reasoning) {
    // 智能提取推理过程的简短摘要（取第一段，最多200字符）
    const reasoningBrief = extractBriefSummary(data.reasoning, 200);

    console.log('📝 推理过程简短摘要提取完成:', reasoningBrief);
    console.log('📝 推理过程简短摘要长度:', reasoningBrief.length);

    html += `
      <div class="ai-check-section">
        <div class="ai-check-label-with-toggle">
          <span>推理过程</span>
          <button class="toggle-btn" data-toggle="reasoning-content" data-icon="reasoning-toggle-icon">
            <span id="reasoning-toggle-icon">▶</span>
          </button>
        </div>
        <div id="reasoning-content" class="ai-check-reasoning markdown-content collapsed">
          <div class="brief-summary">${reasoningBrief}</div>
          <div class="full-content" style="display:none">${parseMarkdown(data.reasoning)}</div>
        </div>
      </div>
    `;
  }

  // AI归纳总结（与普通搜索引擎的核心区别，默认折叠，显示简短摘要）
  if (data.evidence_chain && data.evidence_chain.ai_summary) {
    const aiSummaryData = data.evidence_chain.ai_summary;
    const summaryFull = aiSummaryData.full || aiSummaryData; // 兼容旧格式
    const summaryBrief = aiSummaryData.brief || 'AI深度归纳分析证据，提炼核心事实与洞察';

    console.log('🤖 AI归纳总结 - 完整:', summaryFull);
    console.log('🤖 AI归纳总结 - 简短:', summaryBrief);

    html += `
      <div class="ai-check-section ai-summary-section">
        <div class="ai-check-label-with-toggle ai-summary-label">
          <span>🤖 AI归纳总结</span>
          <button class="toggle-btn" data-toggle="ai-summary-content" data-icon="ai-summary-toggle-icon">
            <span id="ai-summary-toggle-icon">▶</span>
          </button>
        </div>
        <div id="ai-summary-content" class="ai-summary-content markdown-content collapsed">
          <div class="brief-summary" style="color:#5f6368; font-style:italic;">${summaryBrief}</div>
          <div class="full-content" style="display:none">${parseMarkdown(summaryFull)}</div>
        </div>
      </div>
    `;
  }

  // 证据链
  if (data.evidence_chain) {
    console.log('📗 证据链数据:', data.evidence_chain);

    html += `<div class="ai-check-section"><div class="ai-check-label">证据链</div>`;

    // 支持性证据
    if (data.evidence_chain.supporting_evidence && data.evidence_chain.supporting_evidence.length > 0) {
      console.log(`✅ 支持性证据: ${data.evidence_chain.supporting_evidence.length} 条`);
      html += `<div class="evidence-group-title">✅ 支持性证据 (${data.evidence_chain.supporting_evidence.length})</div>`;
      data.evidence_chain.supporting_evidence.forEach((ev, index) => {
        html += createEvidenceCardHTML(ev, 'support', index);
      });
    }

    // 反对性证据
    if (data.evidence_chain.opposing_evidence && data.evidence_chain.opposing_evidence.length > 0) {
      console.log(`❌ 反对性证据: ${data.evidence_chain.opposing_evidence.length} 条`);
      html += `<div class="evidence-group-title">❌ 反对性证据 (${data.evidence_chain.opposing_evidence.length})</div>`;
      data.evidence_chain.opposing_evidence.forEach((ev, index) => {
        html += createEvidenceCardHTML(ev, 'oppose', index);
      });
    }

    // 中性证据
    if (data.evidence_chain.neutral_evidence && data.evidence_chain.neutral_evidence.length > 0) {
      console.log(`⚪ 中性证据: ${data.evidence_chain.neutral_evidence.length} 条`);
      html += `<div class="evidence-group-title">⚪ 中性证据 (${data.evidence_chain.neutral_evidence.length})</div>`;
      data.evidence_chain.neutral_evidence.forEach((ev, index) => {
        html += createEvidenceCardHTML(ev, 'neutral', index);
      });
    }

    html += `</div>`;
  } else {
    console.log('⚠️ 没有证据链数据');
  }

  // 添加操作按钮区
  html += `
    <div class="ai-check-actions">
      <button class="action-btn" id="removeHighlightsBtn">
        🗑️ 清除高亮
      </button>
      <button class="action-btn" id="restoreHighlightsBtn">
        🎨 恢复高亮
      </button>
    </div>
  `;

  result.innerHTML = html;

  // 🔍 调试：检查推理过程的简短摘要是否正确渲染
  const reasoningBriefElement = result.querySelector('#reasoning-content .brief-summary');
  if (reasoningBriefElement) {
    console.log('✅ 推理过程简短摘要DOM元素已找到');
    console.log('📄 推理过程简短摘要HTML内容:', reasoningBriefElement.innerHTML);
    console.log('📏 推理过程简短摘要文本长度:', reasoningBriefElement.textContent.length);
    console.log('👁️ 推理过程简短摘要是否可见:', window.getComputedStyle(reasoningBriefElement).display);
  } else {
    console.error('❌ 推理过程简短摘要DOM元素未找到！');
  }

  // 绑定事件监听器（使用addEventListener代替内联onclick）
  // 绑定推理过程折叠/展开按钮
  const reasoningToggleBtn = result.querySelector('[data-toggle="reasoning-content"]');
  if (reasoningToggleBtn) {
    reasoningToggleBtn.addEventListener('click', () => {
      const sectionId = reasoningToggleBtn.getAttribute('data-toggle');
      const iconId = reasoningToggleBtn.getAttribute('data-icon');
      toggleSection(sectionId, iconId);
    });
  }

  // 绑定AI归纳总结折叠/展开按钮
  const aiSummaryToggleBtn = result.querySelector('[data-toggle="ai-summary-content"]');
  if (aiSummaryToggleBtn) {
    aiSummaryToggleBtn.addEventListener('click', () => {
      const sectionId = aiSummaryToggleBtn.getAttribute('data-toggle');
      const iconId = aiSummaryToggleBtn.getAttribute('data-icon');
      toggleSection(sectionId, iconId);
    });
  }

  // 绑定清除高亮按钮
  const removeBtn = document.getElementById('removeHighlightsBtn');
  if (removeBtn) {
    removeBtn.addEventListener('click', () => {
      removeHighlights();
    });
  }

  // 绑定恢复高亮按钮
  const restoreBtn = document.getElementById('restoreHighlightsBtn');
  if (restoreBtn) {
    restoreBtn.addEventListener('click', () => {
      restoreHighlights(originalClaim);
    });
  }

  // 保存原始claim用于高亮
  result.dataset.originalClaim = originalClaim;
}

// ==================== 从文本中智能提取简短摘要 ====================
function extractBriefSummary(text, maxLength = 200) {
  if (!text) return '暂无内容';

  console.log('🔍 开始提取简短摘要，文本长度:', text.length);

  // 🎯 方案3：组合提取（立场统计 + 证据关系分析）

  // 1. 提取"### 1. 证据立场分析"部分，统计立场分布
  const stanceSectionRegex = /###\s*1[\.、]\s*.*?证据立场分析\s*\n\n([\s\S]+?)(?=\n\n###|$)/;
  const stanceMatch = text.match(stanceSectionRegex);

  let stanceSummary = '';
  if (stanceMatch && stanceMatch[1]) {
    console.log('✅ 匹配到证据立场分析部分');
    const stanceContent = stanceMatch[1];

    // 统计立场关键词数量（匹配格式：**立场**：**支持**、**反对**、**中性**）
    const supportMatches = stanceContent.match(/\*\*立场\*\*[：:]\s*\*\*支持\*\*/g);
    const opposeMatches = stanceContent.match(/\*\*立场\*\*[：:]\s*\*\*反对\*\*/g);
    const neutralMatches = stanceContent.match(/\*\*立场\*\*[：:]\s*\*\*中性\*\*/g);

    const supportCount = supportMatches ? supportMatches.length : 0;
    const opposeCount = opposeMatches ? opposeMatches.length : 0;
    const neutralCount = neutralMatches ? neutralMatches.length : 0;

    const total = supportCount + opposeCount + neutralCount;
    console.log(`📊 立场统计: 支持${supportCount}, 反对${opposeCount}, 中性${neutralCount}, 总计${total}`);

    // 生成立场摘要
    if (total > 0) {
      if (supportCount === total) {
        stanceSummary = `所有${total}个证据均支持该说法`;
      } else if (opposeCount === total) {
        stanceSummary = `所有${total}个证据均反对该说法`;
      } else if (supportCount > opposeCount && supportCount > neutralCount) {
        stanceSummary = `${supportCount}个证据支持该说法，占主导地位`;
      } else if (opposeCount > supportCount && opposeCount > neutralCount) {
        stanceSummary = `${opposeCount}个证据反对该说法，占主导地位`;
      } else {
        stanceSummary = `检索到${total}个证据，立场分布较为均衡`;
      }
    }
  }

  // 2. 提取"### 3. 证据关系分析"的第一行（关系描述）
  const relationshipSectionRegex = /###\s*3[\.、]\s*.*?证据关系分析\s*\n\n([\s\S]+?)(?=\n\n###|$)/;
  const relationshipMatch = text.match(relationshipSectionRegex);

  let relationshipSummary = '';
  if (relationshipMatch && relationshipMatch[1]) {
    console.log('✅ 匹配到证据关系分析部分');
    let relationshipContent = relationshipMatch[1].trim();

    // 清理Markdown符号
    relationshipContent = relationshipContent
      .replace(/^#+\s+/gm, '')
      .replace(/\*\*/g, '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/^>\s+/gm, '')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/^\*\s+/gm, '')
      .replace(/^\-\s+/gm, '')
      .trim();

    // 按换行符分割，取第一个有意义的行
    const lines = relationshipContent.split(/\n/).filter(line => line.trim().length > 20);
    if (lines.length > 0) {
      relationshipSummary = lines[0].trim();
      console.log('📄 证据关系第一行:', relationshipSummary);
    }
  }

  // 3. 组合立场摘要 + 关系摘要
  let combinedSummary = '';
  if (stanceSummary && relationshipSummary) {
    combinedSummary = `${stanceSummary}，${relationshipSummary}`;
    console.log('🔗 组合摘要:', combinedSummary);
  } else if (stanceSummary) {
    combinedSummary = stanceSummary;
  } else if (relationshipSummary) {
    combinedSummary = relationshipSummary;
  }

  // 4. 如果组合成功，返回组合摘要
  if (combinedSummary) {
    if (combinedSummary.length > maxLength) {
      // 截取到第一个句号
      for (let i = maxLength; i >= maxLength * 0.5; i--) {
        if ('。！？.!?'.includes(combinedSummary[i])) {
          const finalSummary = combinedSummary.substring(0, i + 1);
          console.log('✂️ 截取后的组合摘要:', finalSummary);
          return finalSummary;
        }
      }
      // 如果没找到标点，直接截取
      const finalSummary = combinedSummary.substring(0, maxLength - 3) + '...';
      console.log('✂️ 硬截取后的组合摘要:', finalSummary);
      return finalSummary;
    }

    console.log('✅ 最终组合摘要（未超长）:', combinedSummary);
    return combinedSummary;
  }

  // 5. 备用逻辑：如果组合失败，使用原来的方法
  console.log('⚠️ 组合提取失败，使用备用逻辑');

  const paragraphs = text.split(/\n\n+/).filter(p => p.trim());

  let firstContentParagraph = '';
  for (let i = 0; i < paragraphs.length; i++) {
    const para = paragraphs[i].trim();
    if (!para.match(/^#+\s/) && para.length > 10) {
      firstContentParagraph = para;
      break;
    }
  }

  if (!firstContentParagraph) {
    firstContentParagraph = paragraphs[0] || text;
  }

  // 清理Markdown符号
  firstContentParagraph = firstContentParagraph
    .replace(/^#+\s+/gm, '')
    .replace(/\*\*/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^>\s+/gm, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\*\s+/gm, '')
    .trim();

  if (firstContentParagraph.length > maxLength) {
    for (let i = maxLength; i >= maxLength * 0.5; i--) {
      if ('。！？.!?'.includes(firstContentParagraph[i])) {
        return firstContentParagraph.substring(0, i + 1);
      }
    }
    return firstContentParagraph.substring(0, maxLength - 3) + '...';
  }

  return firstContentParagraph || '暂无内容';
}

// ==================== 解析Markdown到HTML ====================
function parseMarkdown(markdown) {
  if (!markdown) return '';

  let html = markdown;

  // 转义HTML（但要保护链接格式）
  html = escapeHtml(html);

  // Markdown解析（简化版）
  // 1. 链接 [文本](url) - 必须先处理，在转义后处理链接
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, url) => {
    return `<a href="${url}" target="_blank" class="markdown-link">${text}</a>`;
  });

  // 2. 标题 ###
  html = html.replace(/###\s+(.*)/g, '<h4 class="md-h4">$1</h4>');
  html = html.replace(/##\s+(.*)/g, '<h3 class="md-h3">$1</h3>');
  html = html.replace(/#\s+(.*)/g, '<h2 class="md-h2">$1</h2>');

  // 3. 粗体 **text**
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="md-strong">$1</strong>');

  // 4. 斜体 *text*
  html = html.replace(/\*([^*]+)\*/g, '<em class="md-em">$1</em>');

  // 5. 引用块 > text
  html = html.replace(/^>\s+(.*)/gm, '<blockquote class="md-blockquote">$1</blockquote>');

  // 6. 列表 - item
  html = html.replace(/^-\s+(.*)/gm, '<li class="md-li">$1</li>');
  // 包裹连续的列表项
  html = html.replace(/(<li[^>]*>.*?<\/li>)(\s*<li[^>]*>|$)/g, '<ul class="md-ul">$1</ul>');

  // 7. 代码 `text`
  html = html.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');

  // 8. 换行处理
  html = html.replace(/\n\n/g, '</p><p class="md-p">');
  html = html.replace(/\n/g, '<br class="md-br">');

  return `<div class="markdown-content">${html}</div>`;
}

// ==================== 创建证据卡片HTML ====================
function createEvidenceCardHTML(evidence, type = 'neutral', index = 0) {
  const scores = evidence.scores || {};
  const url = evidence.url || '#';
  const title = evidence.title || '无标题';
  const summary = evidence.content?.summary || '无摘要';

  return `
    <div class="evidence-card" data-evidence-type="${type}">
      <div class="evidence-header">
        <span class="evidence-rank">#${evidence.rank || index + 1}</span>
        <span class="evidence-tier">${evidence.tier || 'N/A'}</span>
        <span class="evidence-score">${(scores.overall || 0).toFixed(0)}分</span>
      </div>
      <div class="evidence-title" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
      <div class="evidence-summary">${escapeHtml(summary)}</div>
      ${evidence.tags && evidence.tags.length > 0 ? `
        <div class="evidence-tags">
          ${evidence.tags.map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}
        </div>
      ` : ''}
      ${url !== '#' ? `
        <a href="${url}" target="_blank" class="evidence-link" title="${url}">
          🔗 查看原文 →
        </a>
      ` : '<span class="evidence-no-link">无链接</span>'}
    </div>
  `;
}

// ==================== 移除高亮（全局函数） ====================
window.removeHighlights = function() {
  const highlights = document.querySelectorAll('mark.ai-check-highlight');
  highlights.forEach(mark => {
    const text = mark.textContent;
    const parent = mark.parentElement;
    const textNode = document.createTextNode(text);
    parent.replaceChild(textNode, mark);
  });
  document.normalize();
  console.log('✅ 已移除所有高亮');
  showToast('✅ 高亮已清除');
};

// ==================== 恢复高亮（全局函数） ====================
window.restoreHighlights = function(originalClaim) {
  if (!originalClaim) {
    // 如果没有传入参数，尝试从DOM中读取
    const result = document.getElementById('aiCheckResult');
    originalClaim = result?.dataset.originalClaim;
  }

  if (originalClaim) {
    console.log('🎨 恢复高亮:', originalClaim);
    highlightKeywordsInPage(originalClaim);
  } else {
    console.log('⚠️ 没有找到原始claim用于高亮');
  }
};

// ==================== 切换section展开/收起（全局函数） ====================
window.toggleSection = function(sectionId, iconId) {
  console.log('🔄 切换section:', sectionId, iconId);
  const section = document.getElementById(sectionId);
  const icon = document.getElementById(iconId);

  if (section && icon) {
    const isCollapsed = section.classList.contains('collapsed');
    section.classList.toggle('collapsed');
    icon.textContent = isCollapsed ? '▼' : '▶';

    // 切换简短摘要和完整内容的显示
    const briefSummary = section.querySelector('.brief-summary');
    const fullContent = section.querySelector('.full-content');

    if (isCollapsed) {
      // 展开：隐藏简短摘要，显示完整内容
      console.log('📖 展开完整内容');
      if (briefSummary) briefSummary.style.display = 'none';
      if (fullContent) fullContent.style.display = 'block';
    } else {
      // 折叠：显示简短摘要，隐藏完整内容
      console.log('📕 收起，显示简短摘要');
      if (briefSummary) briefSummary.style.display = 'block';
      if (fullContent) fullContent.style.display = 'none';
    }
  }
};

// ==================== 显示错误 ====================
function showError(message) {
  const result = document.getElementById('aiCheckResult');
  result.classList.remove('hidden');
  result.innerHTML = `
    <div class="ai-check-error">
      <div class="error-icon">⚠️</div>
      <p class="error-text">${message}</p>
    </div>
  `;
}

// ==================== HTML转义 ====================
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ==================== 从claim中提取关键词 ====================
function extractKeywords(claim) {
  console.log('🔍 开始提取关键词，原文:', claim);

  // 简单的关键词提取：分割句子，过滤停用词
  const words = claim.split(/[\s,，.。!！?？;；:：、]+/);
  console.log('📝 分词结果:', words);

  const stopWords = ['的', '了', '是', '在', '和', '与', '或', '但', '而', '等', '很', '也', '都', '就', '这', '那', '有', '没有', '什么', '如何', '为什么'];
  console.log('🚫 停用词列表:', stopWords);

  const keywords = words
    .filter(word => {
      const isValid = word.length >= 2 && !stopWords.includes(word);
      if (!isValid && word.length > 0) {
        console.log(`  ❌ 过滤掉: "${word}" (长度:${word.length}, 停用词:${stopWords.includes(word)})`);
      }
      return isValid;
    })
    .filter((word, index, self) => self.indexOf(word) === index) // 去重
    .slice(0, 10); // 最多10个关键词

  console.log('✅ 最终提取的关键词:', keywords);
  return keywords;
}

// ==================== 在页面中高亮关键词 ====================
function highlightKeywordsInPage(claim) {
  const keywords = extractKeywords(claim);
  if (keywords.length === 0) {
    console.log('⚠️ 没有提取到关键词，跳过高亮');
    return;
  }

  console.log('🎨 开始高亮关键词:', keywords);
  console.log('📄 页面body内容长度:', document.body.textContent.length);

  // 移除旧的高亮
  removeOldHighlights();

  // 使用 TreeWalker 遍历文本节点
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode: function(node) {
        // 跳过脚本、样式和已经高亮的内容
        if (node.parentElement.tagName === 'SCRIPT' ||
            node.parentElement.tagName === 'STYLE' ||
            node.parentElement.classList.contains('ai-check-highlight') ||
            node.parentElement.id === 'ai-check-window') {
          return NodeFilter.FILTER_REJECT;
        }
        // 只处理包含关键词的节点
        const text = node.textContent.trim();
        if (text.length === 0) {
          return NodeFilter.FILTER_REJECT;
        }
        if (keywords.some(kw => text.includes(kw))) {
          return NodeFilter.FILTER_ACCEPT;
        }
        return NodeFilter.FILTER_REJECT;
      }
    }
  );

  const nodesToHighlight = [];
  let node;
  while ((node = walker.nextNode())) {
    nodesToHighlight.push(node);
  }

  console.log(`🔍 找到 ${nodesToHighlight.length} 个包含关键词的文本节点`);

  if (nodesToHighlight.length === 0) {
    console.log('⚠️ 没有找到包含关键词的文本节点');
    console.log('💡 可能的原因：');
    console.log('  1. 页面内容中不包含这些关键词');
    console.log('  2. 关键词提取过于严格');
    console.log('  3. 页面还在加载中');
    return;
  }

  // 对每个节点进行高亮
  let highlightedCount = 0;
  nodesToHighlight.forEach((textNode, index) => {
    const parent = textNode.parentElement;
    const content = textNode.textContent;

    // 检查是否包含关键词
    const matchedKeywords = keywords.filter(kw => content.includes(kw));
    if (matchedKeywords.length === 0) return;

    console.log(`  📍 节点 ${index + 1}: 包含关键词 [${matchedKeywords.join(', ')}]`);

    // 创建新的HTML，用mark标签包裹关键词
    let newContent = content;
    keywords.forEach(keyword => {
      const regex = new RegExp(`(${escapeRegExp(keyword)})`, 'gi');
      newContent = newContent.replace(regex, '<mark class="ai-check-highlight">$1</mark>');
    });

    // 如果内容有变化，创建新元素替换
    if (newContent !== content) {
      const span = document.createElement('span');
      span.innerHTML = newContent;
      parent.replaceChild(span, textNode);
      highlightedCount++;
    }
  });

  console.log(`✅ 关键词高亮完成，共高亮 ${highlightedCount} 个位置`);
}

// ==================== 移除旧的高亮 ====================
function removeOldHighlights() {
  const oldHighlights = document.querySelectorAll('mark.ai-check-highlight');
  oldHighlights.forEach(mark => {
    const parent = mark.parentElement;
    parent.replaceChild(document.createTextNode(mark.textContent), mark);
    parent.normalize(); // 合并相邻的文本节点
  });
}

// ==================== 正则表达式转义 ====================
function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ==================== 注入动画样式 ====================
const style = document.createElement('style');
style.textContent = `
  @keyframes slideIn {
    from {
      opacity: 0;
      transform: translateX(100px);
    }
    to {
      opacity: 1;
      transform: translateX(0);
    }
  }

  @keyframes slideOut {
    from {
      opacity: 1;
      transform: translateX(0);
    }
    to {
      opacity: 0;
      transform: translateX(100px);
    }
  }

  @keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }

  /* ========== 核查窗口样式 ========== */
  #ai-check-window {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 2147483647;
    animation: fadeIn 0.3s ease;
  }

  .ai-check-window-overlay {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
  }

  .ai-check-window-container {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 500px;
    max-width: 90vw;
    max-height: 80vh;
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .ai-check-window-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 24px;
    border-bottom: 1px solid #e8eaed;
  }

  .ai-check-window-header h2 {
    margin: 0;
    font-size: 18px;
    font-weight: 500;
    color: #202124;
  }

  .ai-check-close-btn {
    background: none;
    border: none;
    font-size: 24px;
    cursor: pointer;
    color: #5f6368;
    padding: 0;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    transition: background 0.2s;
  }

  .ai-check-close-btn:hover {
    background: #f1f3f4;
  }

  .ai-check-window-body {
    padding: 24px;
    overflow-y: auto;
    max-height: calc(80vh - 80px);
  }

  .ai-check-section {
    margin-bottom: 20px;
  }

  .ai-check-label {
    font-size: 12px;
    font-weight: 500;
    color: #5f6368;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }

  .ai-check-text {
    padding: 12px;
    background: #f8f9fa;
    border-radius: 8px;
    font-size: 14px;
    color: #202124;
    line-height: 1.6;
    word-wrap: break-word;
  }

  .ai-check-btn-primary {
    width: 100%;
    padding: 12px 20px;
    background: #1a73e8;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
  }

  .ai-check-btn-primary:hover:not(:disabled) {
    background: #1557b0;
  }

  .ai-check-btn-primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .ai-check-loading {
    text-align: center;
    padding: 40px 20px;
  }

  .ai-check-spinner {
    width: 40px;
    height: 40px;
    margin: 0 auto 16px;
    border: 3px solid #e8eaed;
    border-top: 3px solid #1a73e8;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  .ai-check-loading p {
    margin: 8px 0;
    font-size: 14px;
  }

  .ai-check-hint {
    color: #5f6368;
    font-size: 12px !important;
  }

  .ai-check-result {
    margin-top: 20px;
  }

  .ai-check-verdict {
    padding: 16px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
  }

  .ai-check-verdict.verdict-true {
    background: #e6f4ea;
  }

  .ai-check-verdict.verdict-false {
    background: #fce8e6;
  }

  .ai-check-verdict.verdict-uncertain {
    background: #fef7e0;
  }

  .verdict-icon {
    font-size: 32px;
    font-weight: bold;
  }

  .verdict-text {
    font-size: 16px;
    font-weight: 500;
    flex: 1;
  }

  .verdict-confidence {
    font-size: 13px;
    opacity: 0.8;
  }

  .ai-check-reasoning {
    padding: 12px;
    background: #f8f9fa;
    border-left: 3px solid #1a73e8;
    border-radius: 4px;
    font-size: 13px;
    color: #3c4043;
    line-height: 1.7;
    white-space: pre-wrap;
  }

  .evidence-group-title {
    font-size: 13px;
    font-weight: 500;
    color: #5f6368;
    margin: 16px 0 8px 0;
  }

  .evidence-card {
    padding: 12px;
    background: #ffffff;
    border: 1px solid #dadce0;
    border-radius: 8px;
    margin-bottom: 8px;
    transition: all 0.2s;
  }

  .evidence-card:hover {
    border-color: #1a73e8;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  }

  .evidence-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    font-size: 12px;
  }

  .evidence-rank {
    font-weight: 600;
    color: #1a73e8;
  }

  .evidence-tier {
    padding: 2px 8px;
    background: #e8f0fe;
    color: #1967d2;
    border-radius: 4px;
    font-weight: 500;
  }

  .evidence-score {
    margin-left: auto;
    color: #5f6368;
  }

  .evidence-title {
    font-size: 14px;
    font-weight: 500;
    color: #202124;
    margin-bottom: 6px;
    line-height: 1.4;
  }

  .evidence-summary {
    font-size: 13px;
    color: #3c4043;
    line-height: 1.6;
    margin-bottom: 8px;
  }

  .evidence-link {
    font-size: 12px;
    color: #1a73e8;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .evidence-link:hover {
    text-decoration: underline;
  }

  .ai-check-error {
    text-align: center;
    padding: 32px 20px;
  }

  .error-icon {
    font-size: 48px;
    margin-bottom: 12px;
  }

  .error-text {
    font-size: 14px;
    color: #c5221f;
    margin: 0;
  }

  .hidden {
    display: none !important;
  }

  mark {
    background-color: #fef7e0;
    border-bottom: 2px solid #f9ab00;
    padding: 2px 4px;
    border-radius: 2px;
  }

  /* ========== 关键词高亮样式 ========== */
  mark.ai-check-highlight {
    background-color: #fff3cd;
    border-bottom: 2px solid #ffc107;
    padding: 2px 4px;
    border-radius: 3px;
    font-weight: 500;
  }

  /* ========== Markdown内容样式 ========== */
  .markdown-content {
    font-size: 13px;
    line-height: 1.8;
    color: #3c4043;
  }

  .markdown-content h2,
  .markdown-content h3,
  .markdown-content h4 {
    margin-top: 16px;
    margin-bottom: 8px;
    font-weight: 500;
    color: #202124;
  }

  .markdown-content h2 {
    font-size: 16px;
  }

  .markdown-content h3 {
    font-size: 14px;
  }

  .markdown-content h4 {
    font-size: 13px;
  }

  .markdown-content strong {
    font-weight: 600;
    color: #202124;
  }

  .markdown-content em {
    font-style: italic;
    color: #5f6368;
  }

  .markdown-content code {
    background: #f1f3f4;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Monaco', 'Courier New', monospace;
    font-size: 12px;
  }

  .markdown-content ul {
    margin: 8px 0;
    padding-left: 20px;
  }

  .markdown-content li {
    margin: 4px 0;
  }

  /* ========== 标签样式 ========== */
  .ai-check-label-with-toggle {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .toggle-btn {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 12px;
    color: #5f6368;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background 0.2s;
  }

  .toggle-btn:hover {
    background: #f1f3f4;
  }

  /* ========== 证据标签 ========== */
  .evidence-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 8px;
  }

  .evidence-tags .tag {
    padding: 2px 8px;
    background: #f1f3f4;
    color: #5f6368;
    border-radius: 4px;
    font-size: 11px;
  }

  .evidence-tags .tag.official {
    background: #e6f4ea;
    color: #137333;
  }

  .evidence-tags .tag.authority {
    background: #e8f0fe;
    color: #1967d2;
  }

  .evidence-no-link {
    font-size: 12px;
    color: #9aa0a6;
    font-style: italic;
  }

  /* ========== 操作按钮区域 ========== */
  .ai-check-actions {
    display: flex;
    gap: 8px;
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid #e8eaed;
  }

  .action-btn {
    flex: 1;
    padding: 8px 12px;
    background: #f1f3f4;
    color: #3c4043;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: background 0.2s;
  }

  .action-btn:hover {
    background: #e8eaed;
  }

  /* ========== 证据卡片类型样式 ========== */
  .evidence-card[data-evidence-type="support"] {
    border-left: 3px solid #137333;
  }

  .evidence-card[data-evidence-type="oppose"] {
    border-left: 3px solid #c5221f;
  }

  .evidence-card[data-evidence-type="neutral"] {
    border-left: 3px solid #f9ab00;
  }

  /* ========== 滚动条样式 ========== */
  .ai-check-window-body::-webkit-scrollbar {
    width: 6px;
  }

  .ai-check-window-body::-webkit-scrollbar-track {
    background: #f1f3f4;
    border-radius: 3px;
  }

  .ai-check-window-body::-webkit-scrollbar-thumb {
    background: #dadce0;
    border-radius: 3px;
  }

  .ai-check-window-body::-webkit-scrollbar-thumb:hover {
    background: #bdc1c6;
  }

  /* ========== Markdown内容增强样式 ========== */
  .markdown-content {
    font-size: 13px;
    line-height: 1.8;
    color: #3c4043;
  }

  /* 标题样式 */
  .markdown-content .md-h2,
  .markdown-content .md-h3,
  .markdown-content .md-h4 {
    margin-top: 16px;
    margin-bottom: 8px;
    font-weight: 500;
    color: #202124;
  }

  .markdown-content .md-h2 {
    font-size: 16px;
    border-bottom: 2px solid #e8eaed;
    padding-bottom: 6px;
  }

  .markdown-content .md-h3 {
    font-size: 14px;
    border-left: 3px solid #1a73e8;
    padding-left: 8px;
  }

  .markdown-content .md-h4 {
    font-size: 13px;
    color: #5f6368;
  }

  /* 文本样式 */
  .markdown-content .md-p {
    margin-bottom: 12px;
  }

  /* 粗体 */
  .markdown-content .md-strong {
    font-weight: 600;
    color: #202124;
  }

  /* 斜体 */
  .markdown-content .md-em {
    font-style: italic;
    color: #5f6368;
  }

  /* 引用块 */
  .markdown-content .md-blockquote {
    margin: 12px 0;
    padding: 12px 16px;
    border-left: 4px solid #1a73e8;
    background: #f8f9fa;
    border-radius: 4px;
    font-style: italic;
  }

  /* 链接样式 */
  .markdown-content .markdown-link {
    color: #1a73e8;
    text-decoration: none;
    border-bottom: 1px dotted #1a73e8;
    transition: all 0.2s;
  }

  .markdown-content .markdown-link:hover {
    color: #1557b0;
    text-decoration: none;
    border-bottom: 1px solid #1557b0;
  }

  /* 代码样式 */
  .markdown-content .md-code {
    background: #f1f3f4;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: 'Monaco', 'Courier New', monospace;
    font-size: 12px;
    color: #d93025;
  }

  /* 列表样式 */
  .markdown-content .md-ul {
    margin: 8px 0;
    padding-left: 24px;
  }

  .markdown-content .md-li {
    margin: 6px 0;
    line-height: 1.6;
  }

  /* 换行样式 */
  .markdown-content .md-br {
    margin-bottom: 4px;
  }

  /* ========== AI归纳总结特殊样式 ========== */
  .ai-summary-section {
    background: linear-gradient(135deg, #f8f9fa 0%, #e8f0fe 100%);
    border: 2px solid #1a73e8 !important;
    border-radius: 12px !important;
    padding: 16px !important;
    margin: 16px 0 !important;
    box-shadow: 0 2px 8px rgba(26, 115, 232, 0.15) !important;
  }

  .ai-summary-label {
    background: linear-gradient(135deg, #1a73e8 0%, #4285f4 100%) !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    padding: 10px 16px !important;
    border-radius: 8px !important;
    margin-bottom: 12px !important;
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    box-shadow: 0 2px 4px rgba(26, 115, 232, 0.2) !important;
  }

  .ai-summary-content {
    padding: 12px !important;
    background: #ffffff !important;
    border-radius: 8px !important;
    line-height: 1.9 !important;
    color: #202124 !important;
    font-size: 14px !important;
  }

  /* AI总结中的项目符号优化 */
  .ai-summary-content ul {
    list-style: none !important;
    padding-left: 0 !important;
  }

  .ai-summary-content li {
    position: relative !important;
    padding-left: 24px !important;
    margin: 8px 0 !important;
  }

  .ai-summary-content li::before {
    content: '💡' !important;
    position: absolute !important;
    left: 0 !important;
    top: 0 !important;
    font-size: 14px !important;
  }

  /* AI总结中的标题突出显示 */
  .ai-summary-content strong {
    color: #1a73e8 !important;
    font-weight: 600 !important;
  }

  /* ========== 折叠/展开状态样式 ========== */
  .ai-check-reasoning.collapsed,
  .ai-summary-content.collapsed {
    max-height: none; /* 移除高度限制，改用子元素控制 */
    overflow: visible;
    position: relative;
    padding: 12px !important;
  }

  /* 折叠状态下，简短摘要显示，完整内容隐藏 */
  .ai-check-reasoning.collapsed .brief-summary,
  .ai-summary-content.collapsed .brief-summary {
    display: block !important;
    max-height: none !important; /* 🔧 移除高度限制，确保完整显示 */
    overflow: visible !important;
    font-style: italic !important; /* 🔧 添加斜体样式，更明显 */
    color: #5f6368 !important; /* 🔧 确保文字颜色可见 */
    background: #f8f9fa !important; /* 🔧 添加浅灰背景，更醒目 */
    padding: 8px !important; /* 🔧 添加内边距 */
    border-radius: 4px !important; /* 🔧 添加圆角 */
  }

  .ai-check-reasoning.collapsed .full-content,
  .ai-summary-content.collapsed .full-content {
    display: none !important;
  }

  .brief-summary {
    font-size: 14px;
    line-height: 1.6;
    color: #5f6368;
    display: block; /* 确保默认是block显示 */
  }

  .full-content {
    font-size: 14px;
    line-height: 1.9;
    display: none; /* 默认隐藏 */
  }
`;
document.head.appendChild(style);

// ==================== 页面加载完成后创建按钮 ====================
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', createFloatingButton);
} else {
  createFloatingButton();
}

// ==================== 监听来自Popup的消息 ====================
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log('收到消息:', request);

  // 处理获取选中文字的请求
  if (request.action === 'getSelection') {
    const selectedText = getSelectedText();
    console.log('返回选中的文字:', selectedText);
    sendResponse({ text: selectedText });
  }

  // 处理高亮关键词的请求（未来功能）
  if (request.action === 'highlightKeywords') {
    highlightKeywords(request.keywords);
    sendResponse({ success: true });
  }

  // 返回true表示异步响应
  return true;
});

// ==================== 获取用户选中的文字 ====================
function getSelectedText() {
  const selection = window.getSelection();
  const selectedText = selection.toString().trim();

  // 如果有选中的文字，返回
  if (selectedText) {
    return selectedText;
  }

  // 如果没有选中的文字，尝试获取页面标题或描述
  const title = document.title;
  const metaDescription = document.querySelector('meta[name="description"]')?.content;

  // 优先返回标题，其次返回描述
  return title || metaDescription || '';
}

// ==================== 高亮关键词（未来功能） ====================
function highlightKeywords(keywords) {
  if (!keywords || keywords.length === 0) return;

  console.log('高亮关键词:', keywords);

  // 在页面中查找并高亮关键词
  const body = document.body;
  const walker = document.createTreeWalker(
    body,
    NodeFilter.SHOW_TEXT,
    null,
    false
  );

  const nodesToReplace = [];
  let node;

  while ((node = walker.nextNode())) {
    const text = node.textContent;
    keywords.forEach(keyword => {
      if (text.includes(keyword)) {
        nodesToReplace.push({ node, keyword });
      }
    });
  }

  // 替换节点
  nodesToReplace.forEach(({ node, keyword }) => {
    const span = document.createElement('span');
    span.className = 'ai-fact-check-highlight';
    span.style.backgroundColor = '#fef7e0';
    span.style.borderBottom = '2px solid #f9ab00';
    span.style.padding = '2px 4px';
    span.style.borderRadius = '2px';

    const regex = new RegExp(`(${escapeRegExp(keyword)})`, 'gi');
    span.innerHTML = node.textContent.replace(regex, '<mark>$1</mark>');

    node.parentNode.replaceChild(span, node);
  });
}

// ==================== 正则表达式转义 ====================
function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ==================== 监听用户选择文字 ====================
let selectionTimer = null;

document.addEventListener('mouseup', () => {
  // 防抖处理，避免频繁触发
  clearTimeout(selectionTimer);
  selectionTimer = setTimeout(() => {
    const selectedText = getSelectedText();
    if (selectedText) {
      console.log('用户选择了文字:', selectedText);
      // 可以在这里添加一些实时反馈
    }
  }, 300);
});

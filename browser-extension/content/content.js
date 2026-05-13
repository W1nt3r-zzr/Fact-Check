// ==================== Content Script ====================
// 这个脚本会被注入到所有网页中，负责获取用户选中的文字和显示浮动按钮

// API 地址配置（从 config.js 读取）
const API_BASE = EXT_CONFIG.API_BASE;

console.log('✅ AI信息核查助手 Content Script 已加载');

// ==================== 创建浮动按钮 ====================
function createFloatingButton() {
  // 扩展 reload 后，页面上可能残留旧按钮，但旧 content script 的事件已失效。
  // 重新注入时先移除旧节点，再绑定当前脚本的事件。
  document.getElementById('ai-check-float-btn')?.remove();

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

  // 🔥 动态生成时间提示（基于历史数据）
  function getDynamicTimeHint() {
    try {
      const history = JSON.parse(localStorage.getItem('factcheck_time_history') || '{}');
      if (history.averageTime && history.count >= 2) {
        // 🔥 基于历史平均时间生成动态提示
        const avg = Math.round(history.averageTime);
        const min = Math.max(30, avg - 15);  // 最小不低于30秒
        const max = avg + 20;                 // 最大增加20秒缓冲

        // 🔥 格式化时间显示（秒/分钟转换）
        const formatTime = (seconds) => {
          if (seconds < 60) {
            return `${seconds}秒`;
          } else {
            const mins = Math.floor(seconds / 60);
            const secs = seconds % 60;
            return secs > 0 ? `${mins}分${secs}秒` : `${mins}分钟`;
          }
        };

        const minStr = formatTime(min);
        const maxStr = formatTime(max);
        const avgStr = formatTime(avg);

        // 🔥 生成提示
        const hint = `大约需要${minStr}-${maxStr}（基于最近${history.count}次核查，平均${avgStr}）`;

        console.log(`📊 历史数据: ${history.count}次核查，平均${avg}秒`);
        return hint;
      }
    } catch (e) {
      console.warn('读取历史时间失败，使用默认提示:', e);
    }

    // 🔥 v0.5.4 默认提示（快速模式，首次使用或读取失败）
    return '大约需要2-3分钟，请耐心等待';
  }

  const timeHint = getDynamicTimeHint();
  console.log(`⏱️ 时间提示: ${timeHint}`);

  // 创建窗口容器
  const modal = document.createElement('div');
  modal.id = 'ai-check-window';
  modal.innerHTML = `
    <div class="ai-check-window-overlay" id="aiCheckOverlay"></div>
    <div class="ai-check-window-container">
      <div class="ai-check-window-header">
        <h2>🔍 AI信息核查</h2>
        <div style="display:flex;gap:6px;align-items:center;">
          <button class="collapse-to-sidebar-btn" id="aiCheckCollapseSidebar" title="收起到侧边栏，后台继续核查">收起</button>
          <button class="ai-check-close-btn" id="aiCheckClose">✕</button>
        </div>
      </div>
      <div class="ai-check-window-body">
        <div class="ai-check-section">
          <div class="ai-check-label">待核查内容</div>
          <textarea class="ai-check-text" id="aiCheckClaimInput" rows="3" placeholder="输入要核查的内容">${escapeHtml(text)}</textarea>
          <div class="input-tip">💡 提示：包含具体的时间、地点、人物等信息，核查效果更准确</div>
        </div>

        <button class="ai-check-btn-primary" id="aiCheckStart">
          <span>⚡</span> 开始核查
        </button>

        <!-- 🔥 新增：实时进度显示 -->
        <div id="aiCheckProgress" class="ai-check-progress hidden">
          <div class="progress-bar">
            <div class="progress-fill" id="progressFill"></div>
          </div>
          <p class="progress-text" id="progressText">准备中...</p>
          <div class="queue-status hidden" id="queueStatus"></div>
        </div>

        <!-- 🔥 新增：实时思考过程显示 -->
        <div id="aiCheckThinking" class="ai-check-thinking hidden"></div>

        <div id="aiCheckLoading" class="ai-check-loading hidden">
          <div class="ai-check-spinner"></div>
          <p>正在核查中...</p>
          <p class="ai-check-hint">${timeHint}</p>
        </div>
        <div id="aiCheckResult" class="ai-check-result hidden"></div>
      </div>
    </div>
  `;

  document.body.appendChild(modal);

  // 绑定关闭按钮
  document.getElementById('aiCheckClose').addEventListener('click', closeCheckWindow);
  document.getElementById('aiCheckOverlay').addEventListener('click', closeCheckWindow);

  // 绑定收起到侧边栏按钮（header中）
  const collapseBtnHeader = document.getElementById('aiCheckCollapseSidebar');
  if (collapseBtnHeader) {
    collapseBtnHeader.addEventListener('click', () => {
      const resultEl = document.getElementById('aiCheckResult');
      const claim = getCurrentModalClaim(text);
      const hasCompletedResult = currentCheckResult && resultEl && !resultEl.classList.contains('hidden');
      if (hasCompletedResult) {
        collapseCompletedResultToSidebar(claim, currentCheckResult);
        return;
      }

      console.log('收起到侧边栏，核查继续后台运行');
      // 通知正在运行的核查任务收起到侧边栏
      globalThis._aiCheckCollapsed = true;
      globalThis._aiCheckCollapsedBeforeDone = true;
      globalThis._aiCheckCollapsedClaim = claim;
      closeCheckWindow();
      // 确保侧边栏先创建好，再添加迷你进度
      toggleSidebar(true);
      // 用 requestAnimationFrame 确保侧边栏DOM已渲染
      requestAnimationFrame(() => {
        showSidebarMiniProgress(claim);
        // 立即同步一次当前进度
        if (globalThis._aiCheckSetProgress) {
          globalThis._aiCheckSetProgress();
        }
      });
      // 启动侧边栏专用定时器（每3秒强制同步一次进度，作为兜底）
      if (globalThis._sidebarProgressTimer) clearInterval(globalThis._sidebarProgressTimer);
      globalThis._sidebarProgressTimer = setInterval(() => {
        if (!globalThis._aiCheckCollapsedBeforeDone) {
          clearInterval(globalThis._sidebarProgressTimer);
          return;
        }
        if (globalThis._aiCheckSetProgress) globalThis._aiCheckSetProgress();
      }, 3000);
    });
  }

  // 🔥 v0.6.0 绑定开始核查按钮（SSE流式模式）
  document.getElementById('aiCheckStart').addEventListener('click', async () => {
    const claim = getCurrentModalClaim(text);
    if (!claim) {
      showToast('请输入要核查的内容');
      return;
    }
    console.log('开始核查（SSE流式）:', claim);
    await performCheckRealStream(claim, false); // 流式模式
  });

  console.log('✅ 核查窗口已创建');
}

function getCurrentModalClaim(fallback = '') {
  const input = document.getElementById('aiCheckClaimInput');
  const value = input ? input.value : fallback;
  return String(value || '').trim();
}

// ==================== 关闭核查窗口 ====================
function closeCheckWindow() {
  const window = document.getElementById('ai-check-window');
  if (window) {
    window.classList.add('closing');
    setTimeout(() => { window.remove(); }, 200);
  }
}

// ==================== 执行核查（常规端点模式，性能优化） ====================
// 🔥 v0.5.4 性能优化：从流式端点切换到常规端点
// 性能提升：240秒 → 约113秒（节省53%）
// 原因：常规端点有缓存机制 + 避免流式处理的性能开销
// 🔥 v0.5.4 简化：统一使用快速模式（enable_thinking = false）
async function performCheckStream(text, enable_thinking = false) {
  const loading = document.getElementById('aiCheckLoading');
  const result = document.getElementById('aiCheckResult');
  const startBtn = document.getElementById('aiCheckStart');
  const thinkingOutput = document.getElementById('aiCheckThinking');
  const progressBar = document.getElementById('aiCheckProgress');
  const progressFill = document.getElementById('progressFill');
  const progressText = document.getElementById('progressText');

  // 🔥 浏览器缓存：第一层缓存（最快，0.1秒）
  function getBrowserCacheKey(claim) {
    // 🔧 修复：使用btoa编码，不需要unescape
    return `factcheck_result_${btoa(encodeURIComponent(claim))}`;
  }

  function getFromBrowserCache(claim) {
    return null; // 临时禁用缓存
    try {
      const cacheKey = getBrowserCacheKey(claim);
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        const data = JSON.parse(cached);
        // 检查是否过期（7天）
        if (data.expire && Date.now() < data.expire) {
          console.log('✅ 浏览器缓存命中');
          return data.result;
        } else {
          // 过期，删除
          localStorage.removeItem(cacheKey);
        }
      }
    } catch (e) {
      console.warn('读取浏览器缓存失败:', e);
    }
    return null;
  }

  function saveToBrowserCache(claim, result) {
    return; // 临时禁用缓存
    try {
      const cacheKey = getBrowserCacheKey(claim);
      const expireTime = Date.now() + 7 * 24 * 60 * 60 * 1000; // 7天后过期
      const cacheData = {
        result: result,
        expire: expireTime,
        saved_at: new Date().toISOString()
      };
      localStorage.setItem(cacheKey, JSON.stringify(cacheData));
      console.log('💾 已保存到浏览器缓存（7天有效）');
    } catch (e) {
      console.warn('保存浏览器缓存失败:', e);
    }
  }

  // 🔥 第一步：查询浏览器缓存
  const cachedResult = getFromBrowserCache(text);
  if (cachedResult) {
    // 缓存命中，直接显示结果
    // 🔥 优化：不显示loading，直接显示结果（缓存响应很快）
    startBtn.disabled = true;

    // 模拟一点加载时间（让用户感知到"正在核查"）
    await new Promise(resolve => setTimeout(resolve, 300));

    result.classList.remove('hidden');
    startBtn.disabled = false;
    displayResult(cachedResult, text);
    return; // 提前返回，不调用API
  }

  // 🔥 记录开始时间和阶段信息
  const startTime = Date.now();
  const stages = {
    searching: { start: null, end: null },
    found: { start: null, end: null },
    thinking: { start: null, end: null },
    processing: { start: null, end: null }
  };

  let currentStage = 'searching'; // 当前阶段
  let currentMessage = '正在搜索证据...'; // 当前消息

  // 🔥 从 localStorage 读取历史平均耗时（如果有）
  const getHistoricalAverage = () => {
    try {
      const history = localStorage.getItem('factcheck_time_history');
      if (history) {
        const data = JSON.parse(history);
        return data.averageTime || null;
      }
    } catch (e) {
      console.warn('读取历史耗时失败:', e);
    }
    return null;
  };

  // 🔥 保存本次耗时到历史记录
  const saveTimeHistory = (totalTime) => {
    try {
      const history = JSON.parse(localStorage.getItem('factcheck_time_history') || '{"count":0,"totalTime":0}');
      history.count++;
      history.totalTime += totalTime;
      history.averageTime = history.totalTime / history.count;
      history.lastUpdate = new Date().toISOString();
      localStorage.setItem('factcheck_time_history', JSON.stringify(history));
      console.log(`💾 已保存耗时历史（共${history.count}次，平均${Math.round(history.averageTime)}秒）`);
    } catch (e) {
      console.warn('保存耗时历史失败:', e);
    }
  };

  // 🔥 格式化时间显示
  function formatTime(seconds) {
    if (seconds < 60) {
      return `${Math.round(seconds)}秒`;
    } else {
      const mins = Math.floor(seconds / 60);
      const secs = Math.round(seconds % 60);
      return secs > 0 ? `${mins}分${secs}秒` : `${mins}分钟`;
    }
  }

  // 🔥 智能时间估算
  let historicalAverage = getHistoricalAverage();
  console.log(`📊 历史平均耗时: ${historicalAverage ? Math.round(historicalAverage) + '秒' : '暂无数据，使用默认估算'}`);

  // 🔥 动态计算预计剩余时间
  function updateProgress(stage, message) {
    currentStage = stage;
    currentMessage = message;

    const elapsed = (Date.now() - startTime) / 1000;

    // 记录阶段开始时间
    if (!stages[stage].start) {
      stages[stage].start = Date.now();
    }

    // 🔥 计算预计剩余时间（简化逻辑，确保倒计时正常减少）
    let remaining;

    if (historicalAverage) {
      // 有历史数据：直接用历史平均 - 已用时间
      remaining = Math.max(0, historicalAverage - elapsed);
    } else {
      // 无历史数据：使用默认总时间 - 已用时间
      // 🔥 v0.5.2 优化：从160秒改为120秒（prompt优化后性能提升50%）
      const defaultTotal = 120;
      remaining = Math.max(0, defaultTotal - elapsed);
    }

    const progressMap = {
      searching: '20%',
      found: '40%',
      thinking: '70%',
      processing: '90%'
    };

    progressFill.style.width = progressMap[stage] || '50%';

    // 🔥 优化：根据阶段和时间显示不同的表述
    let timeDisplay = '';

    if (stage === 'searching' || stage === 'found') {
      // 检索证据阶段：显示倒计时
      if (remaining > 5) {
        timeDisplay = `${message}（已用${formatTime(elapsed)}，预计还需${formatTime(remaining)}）`;
      } else if (remaining > 0) {
        timeDisplay = `${message}（已用${formatTime(elapsed)}，即将完成...）`;
      } else {
        timeDisplay = `${message}（已用${formatTime(elapsed)}，完成中...）`;
      }
    } else if (stage === 'thinking') {
      // 深度思考阶段：显示已用时间，淡化剩余时间
      if (remaining > 30) {
        timeDisplay = `${message}（已用${formatTime(elapsed)}，预计还需${formatTime(remaining)}）`;
      } else if (remaining > 10) {
        timeDisplay = `${message}（已用${formatTime(elapsed)}，即将完成思考...）`;
      } else {
        timeDisplay = `${message}（已用${formatTime(elapsed)}，思考完成中...）`;
      }
    } else if (stage === 'processing') {
      // 生成结果阶段：只显示已用时间
      timeDisplay = `${message}（已用${formatTime(elapsed)}，生成中...）`;
    } else {
      // 默认：显示已用和预计时间
      timeDisplay = `${message}（已用${formatTime(elapsed)}，预计还需${formatTime(remaining)}）`;
    }

    progressText.textContent = timeDisplay;
    console.log(`⏱️ [${stage}] ${timeDisplay}`);
  }

  // 🔥 实时计时器（每秒更新时间显示）
  let timerInterval = null;
  function startRealtimeTimer() {
    timerInterval = setInterval(() => {
      updateProgress(currentStage, currentMessage);
    }, 1000); // 每秒更新一次
  }

  function stopRealtimeTimer() {
    if (timerInterval) {
      clearInterval(timerInterval);
      timerInterval = null;
    }
  }

  // 显示进度条和实时输出区域
  // 🔥 优化：只保留详细的进度条，删除简单的loading提示（避免功能重合）
  loading.classList.add('hidden');  // 隐藏简单提示
  result.classList.add('hidden');
  startBtn.disabled = true;
  thinkingOutput.classList.remove('hidden');
  progressBar.classList.remove('hidden');

  thinkingOutput.innerHTML = '<p style="color:#5f6368;">🔍 准备中...</p>';
  updateProgress('searching', '正在搜索证据...');
  startRealtimeTimer(); // 🔥 启动实时计时器

  try {
    console.log('📡 调用常规API（有缓存优化，性能更好）...');
    console.log('⏱️ 开始时间:', new Date(startTime).toLocaleTimeString());

    // 🔥 v0.5.4 性能优化：切换到常规端点，利用三层缓存机制
    // 性能提升：240秒 → 113秒（节省53%）
    // 🔥 v0.5.4 支持快速模式/深度思考模式切换
    const response = await fetch(`${API_BASE}/api/v1/check`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        claim: text,
        enable_thinking: enable_thinking,  // 🔥 根据选择的模式动态设置
        enable_evidence_chain: true
      })
    });

    if (!response.ok) throw new Error(await getApiErrorMessage(response));

    // 🔥 v0.5.4 常规端点：直接解析JSON（不再需要流式读取）
    updateProgress('processing', 'AI正在深度分析证据...');
    thinkingOutput.innerHTML = `
      <div style="text-align:center; padding:20px;">
        <div style="color:#5f6368; margin-bottom:12px; font-weight:500;">🧠 AI正在深度分析...</div>
        <div style="color:#5f6368; font-size:12px;">这需要一些时间，请耐心等待...</div>
      </div>
    `;

    const finalResult = await response.json();
    console.log('✅ 核查完成:', finalResult);

    // 计算总用时
    const totalTime = (Date.now() - startTime) / 1000;
    console.log(`⏱️ 总用时: ${formatTime(totalTime)}`);
    saveTimeHistory(totalTime);

    // 隐藏加载状态
    stopRealtimeTimer();
    loading.classList.add('hidden');
    progressBar.classList.add('hidden');
    thinkingOutput.classList.add('hidden');

    // 显示结果
    result.classList.remove('hidden');
    currentCheckResult = finalResult;
    currentCheckClaim = text;
    displayResult(finalResult, text);

    // 保存到浏览器缓存
    saveToBrowserCache(text, finalResult);

  } catch (error) {
    console.error('❌ 核查失败:', error);
    stopRealtimeTimer();
    thinkingOutput.classList.add('hidden');
    progressBar.classList.add('hidden');
    showError(formatFetchError(error));
  } finally {
    stopRealtimeTimer(); // 🔥 确保计时器被停止
    loading.classList.add('hidden');
    progressBar.classList.add('hidden');
    startBtn.disabled = false;
  }
}

// ==================== 执行核查（SSE流式模式）====================
// 全局状态：用于跨模态窗口生命周期共享流式数据
window._aiCheckStream = {
  fullContent: '',
  thinkingContent: '',
  streamStarted: false,
  claim: '',
  running: false
};

async function performCheckRealStream(text, enable_thinking = false) {
  if (window._aiCheckActiveRequest?.running) {
    showToast('已有核查任务正在进行，请等待完成');
    return;
  }

  const startTime = Date.now();

  // 重置收起状态（新的核查开始）
  window._aiCheckCollapsed = false;
  window._aiCheckCollapsedBeforeDone = false;
  window._aiCheckCollapsedClaim = '';

  // 重置流式状态
  window._aiCheckStream = {
    fullContent: '',
    thinkingContent: '',
    streamStarted: false,
    claim: text,
    running: true
  };

  // 浏览器缓存（与原函数共用）
  function getBrowserCacheKey(claim) {
    return `factcheck_result_${btoa(encodeURIComponent(claim))}`;
  }
  function getFromBrowserCache(claim) {
    return null; // 临时禁用缓存
    try {
      const cached = localStorage.getItem(getBrowserCacheKey(claim));
      if (cached) {
        const data = JSON.parse(cached);
        if (data.expire && Date.now() < data.expire) return data.result;
        else localStorage.removeItem(getBrowserCacheKey(claim));
      }
    } catch (e) {}
    return null;
  }
  function saveToBrowserCache(claim, resultData) {
    return; // 临时禁用缓存
    try {
      localStorage.setItem(getBrowserCacheKey(claim), JSON.stringify({
        result: resultData, expire: Date.now() + 7 * 24 * 60 * 60 * 1000
      }));
    } catch (e) {}
  }

  // 缓存命中直接返回
  const cachedResult = getFromBrowserCache(text);
  if (cachedResult) {
    const _sb = document.getElementById('aiCheckStart');
    const _res = document.getElementById('aiCheckResult');
    if (_sb) _sb.disabled = true;
    await new Promise(r => setTimeout(r, 300));
    if (_res) _res.classList.remove('hidden');
    if (_sb) _sb.disabled = false;
    displayResult(cachedResult, text);
    return;
  }

  const requestController = new AbortController();
  window._aiCheckActiveRequest = {
    running: true,
    claim: text,
    controller: requestController
  };

  function formatTime(seconds) {
    if (seconds < 60) return `${Math.round(seconds)}秒`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return secs > 0 ? `${mins}分${secs}秒` : `${mins}分钟`;
  }

  let currentPercent = '5%';
  let currentMessage = '正在发起请求...';

  function setProgress(percent, message) {
    if (percent) currentPercent = percent;
    if (message) currentMessage = message;
    // 如果已收起到侧边栏，更新侧边栏迷你进度（带已用时间）
    if (window._aiCheckCollapsed) {
      const elapsed = (Date.now() - startTime) / 1000;
      updateSidebarMiniProgress(currentPercent, `${currentMessage}（${formatTime(elapsed)}）`);
      return;
    }
    // 动态查找DOM（模态窗口可能被重新创建）
    const fill = document.getElementById('progressFill');
    const txt = document.getElementById('progressText');
    if (fill) fill.style.width = currentPercent;
    const elapsed = (Date.now() - startTime) / 1000;
    if (txt) txt.textContent = `${currentMessage}（已用${formatTime(elapsed)}）`;
  }

  function updateQueueStatus(queue) {
    if (!queue) return;
    const running = Number(queue.running || 0);
    const queued = Number(queue.queued || 0);
    const maxConcurrent = Number(queue.max_concurrent || 1);
    const activeOthers = Number(queue.active_others || 0);
    const queuedAhead = Number(queue.queued_ahead || 0);
    const position = Number(queue.position || 0);

    const parts = [
      `服务负载 ${running}/${maxConcurrent}`,
      `其他设备运行中 ${activeOthers}`,
      `总排队 ${queued}`
    ];
    if (position > 0) {
      parts.push(`你排第 ${position} 位`);
      parts.push(`前方 ${queuedAhead} 个`);
    }

    if (window._aiCheckCollapsed) {
      const queueText = `服务负载 ${running}/${maxConcurrent}，排队 ${queued}`;
      updateSidebarMiniProgress(currentPercent, `${currentMessage} · ${queueText}`);
      return;
    }

    const queueEl = document.getElementById('queueStatus');
    if (queueEl) {
      queueEl.textContent = parts.join(' · ');
      queueEl.classList.remove('hidden');
    }
  }

  // 全局函数：供收起按钮直接调用，立即同步进度到侧边栏
  window._aiCheckSetProgress = setProgress;

  // 实时计时器：每秒更新已用时间
  let timerInterval = setInterval(() => setProgress(null, null), 1000);

  // 显示进度条
  const _loading = document.getElementById('aiCheckLoading');
  const _result = document.getElementById('aiCheckResult');
  const _startBtn = document.getElementById('aiCheckStart');
  const _thinkingOutput = document.getElementById('aiCheckThinking');
  const _progressBar = document.getElementById('aiCheckProgress');

  if (_loading) _loading.classList.add('hidden');
  if (_result) _result.classList.add('hidden');
  if (_startBtn) _startBtn.disabled = true;
  if (_thinkingOutput) { _thinkingOutput.classList.add('hidden'); _thinkingOutput.innerHTML = ''; }
  if (_progressBar) _progressBar.classList.remove('hidden');
  setProgress('5%', '正在发起请求...');

  // 累积的推理内容存储在 window._aiCheckStream 中
  const stream = window._aiCheckStream;

  try {
    const response = await fetch(`${API_BASE}/api/v1/check/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: requestController.signal,
      body: JSON.stringify({
        claim: text,
        enable_thinking: enable_thinking,
        enable_evidence_chain: true
      })
    });

    if (!response.ok) throw new Error(await getApiErrorMessage(response));

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let lastEventType = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          lastEventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const dataStr = line.slice(6);
          const eventType = lastEventType;

          if (eventType === 'progress' || dataStr.includes('"stage"')) {
            try {
              const data = JSON.parse(dataStr);
              updateQueueStatus(data.queue);
              const stage = data.stage || '';
              let pP = null, pM = null;
              if (stage === 'queued') { pP = '8%'; pM = data.message || '正在排队等待核查资源...'; }
              else if (stage === 'queue_started') { pP = '12%'; pM = data.message || '已进入核查流程...'; }
              else if (stage === 'searching') { pP = '20%'; pM = '正在搜索证据...'; }
              else if (stage === 'found') { pP = '40%'; pM = '开始AI分析...'; }
              else if (stage === 'thinking_start') { pP = '50%'; pM = 'AI正在深度思考...'; }
              else if (stage === 'processing') { pP = '90%'; pM = data.message || '正在生成证据链...'; }
              if (pP) setProgress(pP, pM);
            } catch (e) {}
          } else if (eventType === 'thinking') {
            try {
              const data = JSON.parse(dataStr);
              stream.thinkingContent += data.content || '';
              if (!stream.streamStarted) stream.streamStarted = true;
              if (window._aiCheckCollapsed) {
                setProgress('50%', 'AI正在深度思考...');
                continue;
              }
              const thinkingEl = document.getElementById('aiCheckThinking');
              if (thinkingEl) {
                thinkingEl.classList.remove('hidden');
                thinkingEl.innerHTML = `<div class="streaming-card streaming-card--draft">
                  <div class="streaming-card-header">
                    <span>生成中 · 草稿分析</span>
                    <small>最终以正式报告为准</small>
                  </div>
                  <div class="streaming-card-body">${simpleMarkdownRender(stream.thinkingContent)}<span class="streaming-card-scroll-anchor"></span></div>
                </div>`;
                scrollStreamingDraftToBottom(thinkingEl);
              }
            } catch (e) {}
          } else if (eventType === 'content') {
            try {
              const data = JSON.parse(dataStr);
              stream.fullContent += data.content || '';
              stream.streamStarted = true;
              if (window._aiCheckCollapsed) {
                setProgress('70%', 'AI正在生成分析报告...');
                continue;
              }
              if (stream.fullContent.length > 0) {
                setProgress('70%', 'AI正在生成分析...');
                const thinkingEl = document.getElementById('aiCheckThinking');
                if (thinkingEl) {
                  thinkingEl.classList.remove('hidden');
                  thinkingEl.innerHTML = `<div class="streaming-card streaming-card--draft">
                    <div class="streaming-card-header">
                      <span>生成中 · 报告草稿</span>
                      <small>完成后会整理为正式报告</small>
                    </div>
                    <div class="streaming-card-body">${simpleMarkdownRender(stream.fullContent)}<span class="streaming-card-scroll-anchor"></span></div>
                  </div>`;
                  scrollStreamingDraftToBottom(thinkingEl);
                }
              }
            } catch (e) {}
          } else if (eventType === 'done') {
            // 收到完整结果
            try {
              const finalResult = JSON.parse(dataStr);
              const totalTime = (Date.now() - startTime) / 1000;
              console.log(`SSE流式完成，总耗时: ${formatTime(totalTime)}`);
              clearInterval(timerInterval);
              if (window._sidebarProgressTimer) clearInterval(window._sidebarProgressTimer);
              stream.running = false;

              const sidebarProgress = document.getElementById('sidebarMiniProgress');
              const shouldCompleteInSidebar = window._aiCheckCollapsedBeforeDone || window._aiCheckCollapsed || (
                sidebarProgress && window._aiCheckStream?.claim === text
              );

              if (shouldCompleteInSidebar) {
                completeSidebarCheck(text, finalResult);
              } else {
                window._aiCheckCollapsed = false;
                // 正常模式：在模态窗口显示结果
                const _pBar = document.getElementById('aiCheckProgress');
                const _tOut = document.getElementById('aiCheckThinking');
                const _pFill = document.getElementById('progressFill');
                const _res = document.getElementById('aiCheckResult');

                if (_pBar) _pBar.classList.add('hidden');
                if (_tOut) _tOut.classList.add('hidden');
                if (_pFill) _pFill.style.width = '100%';

                // 显示结果
                if (_res) _res.classList.remove('hidden');
                currentCheckResult = finalResult;
                currentCheckClaim = text;
                displayResult(finalResult, text);

                // 保存缓存
                saveToBrowserCache(text, finalResult);

                // 自动保存到历史记录
                saveToHistory(text, finalResult);

                // 提示用户核查完成
                showToast('✅ 核查完成！结果已显示在上方');
              }
            } catch (e) {
              console.error('解析done数据失败:', e);
            }
          } else if (eventType === 'error') {
            try {
              const data = JSON.parse(dataStr);
              throw new Error(data.message || '流式核查失败');
            } catch (e) {
              throw e;
            }
          }
        }
      }
    }

    // 如果没有收到 done 事件（理论上不应该发生）
    const _res = document.getElementById('aiCheckResult');
    if (_res && !_res.classList.contains('hidden')) return;
    throw new Error('流式响应异常结束');

  } catch (error) {
    console.error('SSE核查失败:', error);
    clearInterval(timerInterval);
    const _tOut = document.getElementById('aiCheckThinking');
    const _pBar = document.getElementById('aiCheckProgress');
    if (_tOut) _tOut.classList.add('hidden');
    if (_pBar) _pBar.classList.add('hidden');
    showError(formatFetchError(error));
  } finally {
    clearInterval(timerInterval);
    if (window._aiCheckActiveRequest?.controller === requestController) {
      window._aiCheckActiveRequest = null;
      stream.running = false;
    }
    const _ld = document.getElementById('aiCheckLoading');
    const _pb = document.getElementById('aiCheckProgress');
    const _sb = document.getElementById('aiCheckStart');
    if (_ld) _ld.classList.add('hidden');
    if (_pb) _pb.classList.add('hidden');
    if (_sb) _sb.disabled = false;
  }
}

// 简易 Markdown 渲染（供流式实时显示）
function simpleMarkdownRender(text) {
  const linkTokens = createMarkdownLinkTokenStore();
  const html = normalizeMarkdownLineBreaks(text)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, linkText, url) => (
      linkTokens.add(displayTextForMarkdownLink(linkText), url, 'style="color:#1a73e8;"')
    ))
    .replace(/https?:\/\/[^\s<>"{}|\\^`§]+/g, (url) => {
      const cleanUrl = normalizeMarkdownUrl(url.replace(/[)\].!?！？]+$/g, ''));
      try {
        const hostname = new URL(cleanUrl).hostname.replace(/^www\./, '');
        return linkTokens.add(hostname, cleanUrl, 'style="color:#1a73e8;"');
      } catch (e) {
        return url;
      }
    })
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
  return linkTokens.restore(html);
}

function normalizeMarkdownLineBreaks(text) {
  if (!text) return '';
  return String(text).replace(/<br\s*\/?>/gi, '\n');
}

function normalizeMarkdownUrl(url) {
  if (!url) return '';
  return String(url)
    .trim()
    .replace(/&quot;[\s\S]*$/i, '')
    .replace(/["']\s+target=[\s\S]*$/i, '')
    .replace(/\s+target=[\s\S]*$/i, '')
    .replace(/[，。；;、]+$/g, '');
}

function createMarkdownLinkTokenStore() {
  const links = [];
  return {
    add(linkText, url, extraAttributes = 'class="markdown-link"') {
      const cleanUrl = normalizeMarkdownUrl(url);
      if (!/^https?:\/\//i.test(cleanUrl)) {
        return escapeHtml(linkText || cleanUrl || '');
      }

      const displayText = linkText || cleanUrl;
      const token = `§§LINK_${links.length}§§`;
      links.push({ text: displayText, url: cleanUrl, extraAttributes });
      return token;
    },
    restore(html) {
      return html.replace(/§§LINK_(\d+)§§/g, (match, index) => {
        const link = links[Number(index)];
        if (!link) return '';
        return `<a href="${escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer" ${link.extraAttributes}>${escapeHtml(link.text)}</a>`;
      });
    },
  };
}

function displayTextForMarkdownLink(linkText) {
  if (!/^https?:\/\//i.test(linkText)) return linkText;
  try {
    return new URL(linkText).hostname.replace(/^www\./, '');
  } catch (e) {
    return linkText;
  }
}

function scrollStreamingDraftToBottom(container) {
  if (!container) return;
  requestAnimationFrame(() => {
    const body = container.querySelector('.streaming-card-body');
    if (body) {
      body.scrollTop = body.scrollHeight;
    }
  });
}

function renderLazyMarkdownDetail(fullEl, markdown) {
  if (!fullEl || fullEl.dataset.rendered === 'true') return;
  fullEl.innerHTML = parseMarkdown(markdown || '');
  fullEl.dataset.rendered = 'true';
}


// ==================== 显示核查结果 ====================
function displayResult(data, originalClaim) {
  const result = document.getElementById('aiCheckResult');
  result.classList.remove('hidden');

  console.log('📊 显示核查结果:', data);

  // 🔍 自动检测内容是否被截断
  function detectTruncation(content, type = 'content') {
    if (!content) return { isTruncated: false, reason: '内容为空' };

    const len = content.length;
    const lastChar = content.slice(-1);

    // 检测1：没有结束标点
    const hasNoEndPunctuation = (
      len > 100 &&
      !lastChar.match(/[。！？.!?，,、、;；]/) &&
      !content.match(/["'」』】）}\)]$/) &&
      !content.match(/[。！？.!?][^"'\]）】】}]\s*$/)
    );

    // 检测2：句子突然中断
    const hasAbruptEnd = (
      len > 100 &&
      content.match(/[,，]\s*$/) &&  // 逗号结尾
      !content.match(/等[等以及]\s*$/)  // 不是"等"字结尾
    );

    // 检测3：列表项不完整
    const hasIncompleteListItem = (
      content.match(/•\s*$/g) ||  // 有未完成的列表项
      content.match(/\d+\.\s*$/)   // 有未完成的编号列表
    );

    // 检测4：内容长度异常短（可能是严重截断）
    const isTooShort = (
      type === 'reasoning' && len < 200 ||
      type === 'summary' && len < 100
    );

    const isTruncated = hasNoEndPunctuation || hasAbruptEnd || hasIncompleteListItem || isTooShort;

    let reason = '';
    if (isTruncated) {
      if (hasNoEndPunctuation) reason = '缺少结束标点';
      else if (hasAbruptEnd) reason = '句子突然中断';
      else if (hasIncompleteListItem) reason = '列表项不完整';
      else if (isTooShort) reason = '内容过短';
    }

    return { isTruncated, reason };
  }

  let html = '';
  let summaryDetailMarkdown = '';
  let reasoningDetailMarkdown = '';

  // === 1. AI归纳总结 Hero 卡片 ===
  if (data.evidence_chain && data.evidence_chain.ai_summary) {
    const aiSummaryData = data.evidence_chain.ai_summary;
    const summaryBrief = aiSummaryData.brief || 'AI深度归纳分析证据，提炼核心事实与洞察';
    let summaryFull = aiSummaryData.full || '';
    const summaryEvidenceCount = data.evidence_chain.total_evidence ||
      ((data.evidence_chain.supporting_evidence?.length || 0) +
       (data.evidence_chain.opposing_evidence?.length || 0) +
       (data.evidence_chain.neutral_evidence?.length || 0));
    const summaryMeta = summaryEvidenceCount > 0 ? `基于 ${summaryEvidenceCount} 条核心证据` : '综合证据分析';

    // 完整报告中去除开头摘要部分，避免重复
    if (summaryFull && summaryBrief && summaryFull.startsWith(summaryBrief)) {
      summaryFull = summaryFull.substring(summaryBrief.length).trim();
      // 去掉开头的换行和标点
      summaryFull = summaryFull.replace(/^[\n\r\s，,。.、]+/, '');
    }
    summaryDetailMarkdown = normalizeAISummaryMarkdown(summaryFull);

    html += `
      <div class="analysis-panel hero-summary">
        <div class="analysis-panel-header">
          <div>
            <div class="analysis-panel-kicker">AI归纳总结</div>
            <div class="analysis-panel-title">关键结论</div>
          </div>
          <span class="analysis-panel-meta">${summaryMeta}</span>
        </div>
        <div class="hero-summary-brief analysis-brief">${escapeHtml(summaryBrief)}</div>
        ${summaryFull && summaryFull.length > 10 ? `
          <button class="hero-expand-btn analysis-expand-btn" id="heroSummaryExpand">展开详细分析 ▼</button>
          <div class="hero-summary-full markdown-content" id="heroSummaryFull" style="display:none">
          </div>
        ` : ''}
      </div>
    `;
  }

  // === 2. 准备 Tab 数据 ===
  const reasoningContent = data.reasoning || data.thinking_process;
  const ec = data.evidence_chain;
  const supportCount = ec?.supporting_evidence?.length || 0;
  const opposeCount = ec?.opposing_evidence?.length || 0;
  const neutralCount = ec?.neutral_evidence?.length || 0;
  const totalEvidence = supportCount + opposeCount + neutralCount;

  // 证据解读摘要：从GLM分析文本的第3节（证据关系分析）提取，与AI归纳总结互补
  let reasoningBrief = '';
  if (reasoningContent) {
    reasoningBrief = buildReasoningBrief(reasoningContent, ec);
  }

  // === 3. Tab 栏 ===
  html += `
    <div class="tab-bar">
      <button class="tab-item tab-active" data-tab="evidence">证据链 (${totalEvidence})</button>
      <button class="tab-item" data-tab="reasoning">证据解读</button>
    </div>
  `;

  // === 4. 证据 Tab 内容 ===
  html += `<div class="tab-content" id="tab-evidence">`;

  if (totalEvidence > 0) {
    // 证据检索与质量说明
    const totalSearchResults = ec?.total_search_results || 0;
    html += buildEvidenceOverviewHtml(totalSearchResults, totalEvidence, ec?.reasoning_summary, ec?.all_search_results);

    html += `
      <div class="stats-row">
        <div class="stat-card stat-support">
          <span class="stat-num">${supportCount}</span>
          <span class="stat-label">支持</span>
        </div>
        <div class="stat-card stat-oppose">
          <span class="stat-num">${opposeCount}</span>
          <span class="stat-label">反对</span>
        </div>
        <div class="stat-card stat-neutral">
          <span class="stat-num">${neutralCount}</span>
          <span class="stat-label">中性</span>
        </div>
      </div>
    `;

    html += `<div class="evidence-grid">`;
    let evidenceDisplayIndex = 1;

    if (supportCount > 0) {
      html += `<section class="evidence-section evidence-section-support">
        <div class="evidence-group-title">✅ 支持性证据</div>`;
      ec.supporting_evidence.forEach((ev, i) => { html += createEvidenceCardHTML(ev, 'support', i, evidenceDisplayIndex++); });
      html += `</section>`;
    }
    if (opposeCount > 0) {
      html += `<section class="evidence-section evidence-section-oppose">
        <div class="evidence-group-title evidence-group-oppose">❌ 反对性证据</div>`;
      ec.opposing_evidence.forEach((ev, i) => { html += createEvidenceCardHTML(ev, 'oppose', i, evidenceDisplayIndex++); });
      html += `</section>`;
    }
    if (neutralCount > 0) {
      html += `<section class="evidence-section evidence-section-neutral">
        <div class="evidence-group-title evidence-group-neutral">⚪ 中性证据</div>`;
      ec.neutral_evidence.forEach((ev, i) => { html += createEvidenceCardHTML(ev, 'neutral', i, evidenceDisplayIndex++); });
      html += `</section>`;
    }

    html += `</div>`;
  } else {
    html += `<div class="tab-empty">暂无证据数据</div>`;
  }

  html += `</div>`;

  // === 5. 证据解读 Tab 内容 ===
  html += `<div class="tab-content" id="tab-reasoning" style="display:none">`;

  if (reasoningContent) {
    const reasoningDisplayContent = buildReasoningDisplayContent(reasoningContent, ec);
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
        <div class="reasoning-brief">${renderInlineMarkdown(reasoningBrief)}</div>
        <button class="hero-expand-btn analysis-expand-btn" id="reasoningExpand">展开引用、关系与局限 ▼</button>
        <div class="reasoning-full markdown-content" id="reasoningFull" style="display:none">
        </div>
      </div>
    `;
  } else {
    html += `<div class="tab-empty">暂无证据解读</div>`;
  }

  html += `</div>`;

  html += '</div>'; // 关闭最后一个 tab-content

  // 收起到侧边栏按钮
  html += '<div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #e8eaed; text-align: center;">';
  html += '<button class="collapse-to-sidebar-btn" id="collapseToSidebarBtn">收起到侧边栏</button>';
  html += '</div>';

  result.innerHTML = html;
  result.removeEventListener('click', handleEvidenceAnchorClick);
  result.addEventListener('click', handleEvidenceAnchorClick);

  // === 事件绑定 ===

  // Hero 展开按钮
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

  // 证据解读展开按钮
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

  // Tab 切换
  document.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('tab-active'));
      tab.classList.add('tab-active');
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
      const target = document.getElementById('tab-' + tab.dataset.tab);
      if (target) target.style.display = 'block';
    });
  });

  result.dataset.originalClaim = originalClaim;

  // 收起到侧边栏按钮
  const collapseBtn = document.getElementById('collapseToSidebarBtn');
  if (collapseBtn) {
    collapseBtn.addEventListener('click', () => {
      collapseCompletedResultToSidebar(originalClaim, currentCheckResult || data);
    });
  }

  // === 对结果区域内的文本进行关键词高亮 ===
  highlightKeyContent(result, data, originalClaim);
}

// ==================== 插件内关键词高亮 ====================
function highlightKeyContent(container, data, claim) {
  if (!container || !claim) return;

  // 1. 从 claim 中提取核心实体
  const keywords = extractHighlightKeywords(claim, data, container.textContent || '');
  if (keywords.length === 0) return;
  const highlightStats = new WeakMap();
  const MAX_HIGHLIGHTS_IN_FULL_REPORT = 160;
  const MAX_HIGHLIGHTS_PER_FULL_REPORT_BLOCK = 10;

  // 2. 在指定容器内的文本节点中高亮
  const walker = document.createTreeWalker(
    container,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode: function(node) {
        const tag = node.parentElement.tagName;
        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') {
          return NodeFilter.FILTER_REJECT;
        }
        // 跳过已有高亮的节点和链接
        if (node.parentElement.classList.contains('kw-highlight') ||
            node.parentElement.classList.contains('evidence-highlight') ||
            node.parentElement.tagName === 'A' ||
            node.parentElement.tagName === 'BUTTON' ||
            node.parentElement.classList.contains('stance-tag') ||
            node.parentElement.closest('h1, h2, h3, h4, h5, h6') ||
            node.parentElement.closest('.md-h2, .md-h3, .md-h4') ||
            node.parentElement.closest('.analysis-panel-title, .analysis-panel-kicker') ||
            node.parentElement.closest('.evidence-group-title') ||
            node.parentElement.closest('.evidence-title') ||
            node.parentElement.closest('.evidence-source') ||
            node.parentElement.closest('.evidence-summary') ||
            node.parentElement.closest('.evidence-focus') ||
            node.parentElement.closest('.analysis-panel-meta')) {
          return NodeFilter.FILTER_REJECT;
        }
        const text = node.textContent.trim();
        if (text.length < 2) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);

  nodes.forEach(textNode => {
    const content = textNode.textContent;
    const matches = [];
    const fullReport = textNode.parentElement.closest('.reasoning-full, .hero-summary-full');

    keywords.forEach((kw, keywordIndex) => {
      const keywordMatches = findKeywordMatches(content, kw);
      keywordMatches.forEach(({ start, end }) => {
        matches.push({
          start,
          end,
          text: kw,
          weight: keywords.length - keywordIndex,
        });
      });
    });

    if (matches.length === 0) return;

    // 去重叠：长词优先
    matches.sort((a, b) => a.start - b.start || b.text.length - a.text.length);
    let filtered = [];
    let lastEnd = -1;
    matches.forEach(m => {
      if (m.start >= lastEnd) { filtered.push(m); lastEnd = m.end; }
    });

    if (filtered.length === 0) return;

    if (fullReport) {
      const currentTotal = highlightStats.get(fullReport) || 0;
      if (currentTotal >= MAX_HIGHLIGHTS_IN_FULL_REPORT) return;

      filtered = filtered
        .sort((a, b) => b.weight - a.weight || b.text.length - a.text.length || a.start - b.start)
        .slice(0, Math.min(MAX_HIGHLIGHTS_PER_FULL_REPORT_BLOCK, MAX_HIGHLIGHTS_IN_FULL_REPORT - currentTotal))
        .sort((a, b) => a.start - b.start);

      if (filtered.length === 0) return;
      highlightStats.set(fullReport, currentTotal + filtered.length);
    }

    const parent = textNode.parentElement;
    const span = document.createElement('span');
    let lastIdx = 0;

    filtered.forEach(m => {
      if (m.start > lastIdx) {
        span.appendChild(document.createTextNode(content.substring(lastIdx, m.start)));
      }
      const mark = document.createElement('span');
      mark.className = 'kw-highlight';
      mark.title = '核查关键词';
      mark.textContent = content.substring(m.start, m.end);
      span.appendChild(mark);
      lastIdx = m.end;
    });

    if (lastIdx < content.length) {
      span.appendChild(document.createTextNode(content.substring(lastIdx)));
    }

    parent.replaceChild(span, textNode);
  });
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isCjkChar(char) {
  return /[一-鿿]/.test(char);
}

function buildFlexibleChineseKeywordRegex(keyword) {
  if (!/[一-鿿]/.test(keyword) || keyword.length < 4) return null;

  const chars = Array.from(keyword);
  const pattern = chars.map((char, index) => {
    const next = chars[index + 1];
    const gap = next && isCjkChar(char) && isCjkChar(next) ? '[\\s\\u00a0]*' : '';
    return `${escapeRegExp(char)}${gap}`;
  }).join('');

  return new RegExp(pattern, 'g');
}

function findKeywordMatches(content, keyword) {
  const matches = [];
  const seen = new Set();

  function addMatch(start, end) {
    if (start < 0 || end <= start) return;
    const key = `${start}:${end}`;
    if (seen.has(key)) return;
    seen.add(key);
    matches.push({ start, end });
  }

  let searchStart = 0;
  while (true) {
    const idx = content.indexOf(keyword, searchStart);
    if (idx === -1) break;
    addMatch(idx, idx + keyword.length);
    searchStart = idx + keyword.length;
  }

  const flexibleRegex = buildFlexibleChineseKeywordRegex(keyword);
  if (flexibleRegex) {
    let match;
    while ((match = flexibleRegex.exec(content)) !== null) {
      addMatch(match.index, match.index + match[0].length);
      if (match[0].length === 0) flexibleRegex.lastIndex += 1;
    }
  }

  return matches.sort((a, b) => a.start - b.start || b.end - a.end);
}

function buildEvidenceOverviewHtml(totalSearchResults, totalEvidence, reasoningSummary, allSearchResults) {
  const lines = [];
  if (totalSearchResults > totalEvidence) {
    lines.push(`检索到 ${totalSearchResults} 个结果，其中 ${totalEvidence} 个与待核查说法匹配度较高，已作为核心证据进行分析；其余结果可能为重复转载、背景信息或相关性较弱内容。`);
  } else if (totalEvidence > 0) {
    lines.push(`已选取 ${totalEvidence} 条核心证据进行分析。`);
  }

  const qualitySummary = stripEvidenceCountLead(reasoningSummary);
  if (qualitySummary) {
    lines.push(qualitySummary);
  }

  let allSourcesHtml = '';
  if (Array.isArray(allSearchResults) && allSearchResults.length > 0) {
    const uniqueDomains = [];
    const seen = new Set();
    allSearchResults.forEach(r => {
      const domain = r.domain || '';
      if (domain && !seen.has(domain)) {
        seen.add(domain);
        uniqueDomains.push({ domain, title: r.title || '' });
      }
    });
    if (uniqueDomains.length > 0) {
      const sourceItems = uniqueDomains.map((item, idx) =>
        `<span class="all-source-item" title="${escapeHtml(item.title)}">${escapeHtml(item.domain)}</span>`
      ).join(' · ');
      allSourcesHtml = `
        <div class="all-sources-row">
          <span class="all-sources-label">全部来源</span>
          <span class="all-sources-list">${sourceItems}</span>
        </div>`;
    }
  }

  return lines.length
    ? `<div class="evidence-retrieval-info">📊 ${lines.map(line => renderInlineMarkdown(line)).join('<br>')}${allSourcesHtml}</div>`
    : '';
}

function stripEvidenceCountLead(text) {
  return String(text || '')
    .replace(/^共检索到\d+条证据，覆盖\d+个不同域名来源。\s*/u, '')
    .trim();
}

// 从 claim 和证据中提取需要高亮的关键词
function extractHighlightKeywords(claim, data, reportText = '') {
  const kwSet = new Set();
  const kwPriority = new Map();

  // 停用词
  const stopWords = new Set([
    '的', '了', '是', '在', '和', '与', '或', '但', '而', '等', '很', '也', '都', '就',
    '有', '被', '把', '让', '给', '向', '从', '到', '对', '为', '以', '之', '这', '那',
    '可以', '可能', '因为', '所以', '但是', '然而', '如果', '已经', '正在', '没有', '不是',
    '一个', '什么', '怎么', '如何', '通过', '进行', '关于', '包括', '其中', '对于', '目前',
    '根据', '显示', '表示', '认为', '指出', '说明', '报道', '来自', '需要', '能够', '应该',
    '必须', '虽然', '不过', '而且', '或者', '以及', '所有', '一些', '每个', '任何', '非常',
    '比较', '更加', '主要', '重要', '关键', '核心', '基本', '相关', '不同', '同时', '因此',
    '只是', '还是', '发生', '出现', '成为', '开始', '之后', '之前', '来说', '起来', '出来',
    '得到', '该', '其', '此', '某', '些', '那', '中', '上', '下', '内', '外', '前', '后',
    '他说', '她说', '表示', '声称', '指出', '认为', '发现', '是否', '真的',
    '网传', '传言', '网友', '消息', '相关', '情况', '内容', '信息', '记者',
  ]);

  // 实体前缀边界：排除常见动词、介词、代词、连词、副词，
  // 否则机构名正则会把"核心驱动是公司""报道所指为A股上市公司"这类语义片段误识别为机构名。
  // 注意"有"在边界列表内，因此组合后缀(股份有限公司|有限责任公司|有限公司)必须排在前面，
  // 才能让正则在前缀停在"有"之前时仍匹配到完整的"X股份有限公司"。
  const ENTITY_BREAKER_CHARS = '是为的了着被把与和或及并跟同在有由从向到对以于比给因这那此其该也还就再又都已即便要会能';
  const ENTITY_PREFIX_CHAR = `(?:[A-Za-z0-9]|(?![${ENTITY_BREAKER_CHARS}])[一-鿿])`;
  const ORG_SUFFIX_FULL = '股份有限公司|有限责任公司|有限公司|公司|集团|股份|科技|大学|银行|证券|基金|交易所|研究院|部门|机构|税务局|税务总局|总局|管理局|委员会|卫健委|统计局|法院|警方|迪士尼';
  const ORG_SUFFIX_CLAIM = '股份有限公司|有限责任公司|有限公司|公司|集团|股份|科技|大学|银行|证券|基金|交易所|研究院|部门|机构|税务局|卫健委|统计局|法院|警方|迪士尼';
  const ORG_SUFFIX_TITLE = '股份有限公司|有限责任公司|有限公司|公司|集团|股份|科技|大学|银行|证券|基金|交易所|研究院|部门|机构';
  const ORG_REGEX_FULL = new RegExp(`${ENTITY_PREFIX_CHAR}{2,14}(?:${ORG_SUFFIX_FULL})`, 'g');
  const ORG_REGEX_CLAIM = new RegExp(`${ENTITY_PREFIX_CHAR}{2,12}(?:${ORG_SUFFIX_CLAIM})`, 'g');
  const ORG_REGEX_TITLE = new RegExp(`${ENTITY_PREFIX_CHAR}{2,8}(?:${ORG_SUFFIX_TITLE})`, 'g');

  function addKeyword(value, priority = 10) {
    const kw = String(value || '').trim().replace(/^[，,。.！!？?；;：:、\s]+|[，,。.！!？?；;：:、\s]+$/g, '');
    if (kw.length < 2 || stopWords.has(kw)) return;
    if (/^[年月日元万亿元%％]+$/.test(kw)) return;
    if (/^(?:核心事实提取|终审结果确定|最终判决内容|关键量刑情节|案件性质)$/.test(kw)) return;
    if (/^(?:并|和|与|及)/.test(kw) || /(?:并|和|与|及)$/.test(kw)) return;
    if (kw.length <= 4 && (/(?:最终|部分|原因)/.test(kw) || (/性影像$/.test(kw) && !/^未成年/.test(kw)))) return;
    kwSet.add(kw);
    kwPriority.set(kw, Math.max(kwPriority.get(kw) || 0, priority));
  }

  function collectImportantTerms(text, priority = 70) {
    if (!text) return;
    (text.match(/\d{4}年(?:至|到|-|—)\d{4}年(?:间|期间)?/g) || [])
      .forEach(e => {
        addKeyword(e, priority + 8);
        addKeyword(e.replace(/(?:间|期间)$/, ''), priority + 9);
      });
    (text.match(/\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?/g) || [])
      .forEach(e => addKeyword(e, priority + 7));
    (text.match(/\d{1,2}月\d{1,2}日/g) || [])
      .forEach(e => addKeyword(e, priority + 6));
    (text.match(/\d{4}年/g) || [])
      .forEach(e => addKeyword(e, priority + 4));
    (text.match(/\d+(?:\.\d+)?(?:万|亿|千|百)?(?:元|美元|人民币|税款|罚款|人|例|次|条|台|辆|级|%|％)/g) || [])
      .forEach(e => addKeyword(e, priority + 8));
    (text.match(/(?:偷逃税款|少缴税款|补缴税款|处罚款|被罚|罚款|追缴|临时闭园|恢复开放|新增确诊|新增病例|未检出|不存在|不属实|属实|已证实|已辟谣|无法证实|依法查处|查处|转换收入性质|虚假申报|少缴|通报显示|核心结论|关键事实|权威来源|证据显示|证据表明|官方通报|处理结果|调查结果|事实依据)/g) || [])
      .forEach(e => addKeyword(e, priority + 5));
    (text.match(/(?:(?:大量|多(?:部|张|段|个)?|数(?:部|张|段)?|\d+部))?(?:未成年|未成年人)(?:青少年|儿童|少女|女童)?[一-鿿\s\u00a0]{0,4}(?:性影像|影像|视频|照片|图像)/g) || [])
      .forEach(e => {
        const normalized = e.replace(/[\s\u00a0]+/g, '');
        const coreSexImage = normalized.match(/^(.*?性影像)(?:视频|照片|图像|影像)?$/)?.[1] || normalized;
        addKeyword(normalized, priority + 10);
        addKeyword(coreSexImage, priority + 10);
        addKeyword(coreSexImage.replace(/^(?:大量|多(?:部|张|段|个)?|数(?:部|张|段)?|\d+部)/, ''), priority + 9);
      });
    (text.match(/(?:(?:台湾|台媒|香港|澳门|内地|大陆|中国))?(?:艺人|演员|歌手|主持人|网红|博主|导演|作家|专家|医生)[一-鿿]{2,4}(?=在|因|被|偷|少缴|处罚|罚款|涉嫌|称|表示|回应|发布|通报|收藏|持有|下载|获|遭|一审|二审|终审|$)/g) || [])
      .forEach(e => {
        const normalized = e.replace(/^台媒/, '台湾');
        addKeyword(normalized, priority - 5);
        if (/^(?:台湾|香港|澳门|内地|大陆|中国)/.test(normalized)) {
          addKeyword(normalized.replace(/^(?:台湾|香港|澳门|内地|大陆|中国)/, ''), priority - 4);
        }
      });
    (text.match(/(?:有期徒刑|缓刑|拘役|管制)\d+年(?:\d+个月)?/g) || [])
      .forEach(e => addKeyword(e, priority + 9));
    (text.match(/(?:一审|二审|三审|第三审|终审|再审)/g) || [])
      .forEach(e => {
        addKeyword(e, priority + 8);
        if (e === '三审') addKeyword('第三审', priority + 8);
        if (e === '第三审') addKeyword('三审', priority + 7);
      });
    (text.match(/包含[^，。,；;]{0,12}(?:姓名|学校|个人资料)[^，。,；;]{0,12}(?:个人资料|拍摄)/g) || [])
      .forEach(e => {
        addKeyword(e, priority + 8);
        addKeyword(e.replace(/拍摄$/, ''), priority + 9);
      });
    (text.match(/个人资料拍摄/g) || [])
      .forEach(e => addKeyword(e, priority + 10));
    (text.match(/(?:检方|被告|原告|法院|最高法院|检察官)?上诉/g) || [])
      .forEach(e => addKeyword(e, priority + 8));
    (text.match(/驳回[^，。,；;]{0,8}上诉/g) || [])
      .forEach(e => {
        addKeyword(e, priority + 10);
        const appealMatch = e.match(/(检方|被告|原告|法院|最高法院)?上诉/);
        if (appealMatch) addKeyword(appealMatch[0], priority + 8);
      });
    (text.match(/(?:全案|案件|判决)[^，。,；;]{0,4}(?:确定|定谳)/g) || [])
      .forEach(e => addKeyword(e, priority + 9));
    (text.match(/(?:缓刑|判决|裁定)?定谳/g) || [])
      .forEach(e => addKeyword(e, priority + 9));
    (text.match(/(?:不需|无需|不用|免于)[^，。,；;]{0,6}(?:入狱|服刑|入狱服刑)/g) || [])
      .forEach(e => addKeyword(e, priority + 9));
    (text.match(/(?:改口)?认罪/g) || [])
      .forEach(e => addKeyword(e, priority + 8));
    (text.match(/(?:被害人|受害人|当事人)[^，。,；;]{0,8}(?:和解|调解|协商|洽谈)/g) || [])
      .forEach(e => addKeyword(e, priority + 8));
    (text.match(/(?:出台|制定|建立|形成|缺乏|尚未出台|未出台)[一-鿿]{0,12}(?:生产标准和检测规范|检测规范|生产标准|统一标准|行业标准|国家标准|检验规范|监管规范)/g) || [])
      .forEach(e => {
        addKeyword(e, priority + 8);
        addKeyword(e.replace(/^(?:尚未|未)/, ''), priority + 9);
      });
    (text.match(/[一-鿿]{2,18}(?:生产标准和检测规范|检测规范|生产标准|统一标准|行业标准|国家标准|检验规范|监管规范)/g) || [])
      .forEach(e => addKeyword(e, priority + 6));
    (text.match(ORG_REGEX_FULL) || [])
      .forEach(e => addKeyword(e, priority + 3));
    (text.match(/(?:国家|中国|上海|北京|广东|浙江|江苏|四川|湖北|湖南|山东|河南|河北|福建|深圳|广州)[一-鿿]{2,12}(?:发布|通报|公告|披露|回应|证实|辟谣)/g) || [])
      .forEach(e => addKeyword(e.replace(/(?:发布|通报|公告|披露|回应|证实|辟谣)$/, ''), priority + 4));
    (text.match(/[一-鿿]{2,4}(?=通过|被|已被|因|涉嫌|少缴|偷逃|处罚|罚款|查处|回应|承认)/g) || [])
      .forEach(e => addKeyword(e, priority + 2));
    (text.match(/[一-鿿]{2,10}(?:性质|申报|收入|税款|罚款|滞纳金|闭园|病例|检测|抽检|处罚|追缴|证据|结论)/g) || [])
      .forEach(e => addKeyword(e, priority + 1));
  }

  // 1. 高优先级：核查结论通常依赖的硬事实
  collectImportantTerms(claim, 92);

  // 2. 主体/地点/机构：短但关键，单纯按长度排序会漏掉
  (claim.match(/(?:网红|博主|演员|歌手|专家|医生|学生|男孩|女孩|品牌|公司)?([一-鿿]{2,4})(?=在|因|被|偷|少缴|处罚|罚款|涉嫌|称|表示|回应|发布|通报)/g) || [])
    .forEach(e => addKeyword(e.replace(/^(网红|博主|演员|歌手|专家|医生|学生|男孩|女孩|品牌|公司)/, ''), 88));
  (claim.match(ORG_REGEX_CLAIM) || [])
    .forEach(e => addKeyword(e, 86));
  (claim.match(/[一-鿿]{2,8}(?:市|省|县|区|镇|机场|学校|医院|景区|乐园|口岸|港口)/g) || [])
    .forEach(e => addKeyword(e, 84));

  // 3. 从 claim 提取：按标点分段（2-12字），作为补充候选
  claim.split(/[，,。.！!？?；;：:、\s\n\r\t「」""''【】\[\]()（）\-—…·]+/)
    .filter(seg => seg.length >= 2 && seg.length <= 12 && !stopWords.has(seg))
    .forEach(seg => addKeyword(seg, 45));

  // 4. 数字+单位组合（如"7.7级""2026年"）
  (claim.match(/\d+\.?\d*[万亿千百%％指数点级倍年月日人次条个]*[一-鿿]?/g) || [])
    .filter(e => e.length >= 2 && e.length <= 12)
    .forEach(e => addKeyword(e, 65));

  // 5. 从证据标题中提取专有名词
  const ec = data?.evidence_chain;
  const allEvidence = [
    ...(ec?.supporting_evidence || []),
    ...(ec?.opposing_evidence || []),
    ...(ec?.neutral_evidence || [])
  ];

  allEvidence.forEach(ev => {
    const title = ev.title || '';
    // 机构名（XX公司、XX集团等）
    (title.match(ORG_REGEX_TITLE) || [])
      .forEach(e => addKeyword(e, 55));
    // 人名（2-4字中文，通常在标题开头或"某某表示"中）
    const nameMatch = title.match(/([一-鿿]{2,4})(?:表示|称|指出|认为|透露|透露|回应|透露)/);
    if (nameMatch && !stopWords.has(nameMatch[1])) addKeyword(nameMatch[1], 55);
    (ev.highlights || []).forEach(highlight => collectImportantTerms(highlight.text, 76));
    collectImportantTerms(ev.content?.key_quote || ev.content?.summary || ev.summary || '', 58);
  });

  collectImportantTerms(ec?.ai_summary?.brief || '', 80);
  collectImportantTerms(ec?.reasoning_summary || '', 68);
  (ec?.key_findings || []).forEach(finding => collectImportantTerms(finding, 70));
  collectImportantTerms(reportText, 62);

  // 6. 排序：重要性优先，其次长度和原文位置
  const sortedKeywords = Array.from(kwSet)
    .filter(kw => !stopWords.has(kw) && kw.length >= 2)
    .sort((a, b) => {
      const priorityDiff = (kwPriority.get(b) || 0) - (kwPriority.get(a) || 0);
      if (priorityDiff !== 0) return priorityDiff;
      const lengthDiff = b.length - a.length;
      if (lengthDiff !== 0) return lengthDiff;
      return claim.indexOf(a) - claim.indexOf(b);
    });

  const preciseKeywords = [];
  sortedKeywords.forEach(kw => {
    const keepIfContained = /^(?:检方|被告|原告|法院|最高法院)?上诉$/.test(kw) ||
      /^(?:未成年|未成年人)(?:青少年|儿童|少女|女童)?.*性影像$/.test(kw);
    const isContainedByLonger = preciseKeywords.some(existing => (
      !keepIfContained &&
      existing.includes(kw) &&
      (kwPriority.get(existing) || 0) >= (kwPriority.get(kw) || 0)
    ));
    if (!isContainedByLonger) preciseKeywords.push(kw);
  });

  return preciseKeywords.slice(0, 80); // 面向完整报告阅读，保留更多高价值候选
}

function normalizeAISummaryMarkdown(text) {
  if (!text) return '';

  let normalized = String(text)
    .replace(/\r\n?/g, '\n')
    .replace(/\t/g, '  ')
    .trim();

  // 模型有时会把多个要点压在一行，这里先拆成独立列表行。
  normalized = normalized
    .replace(/([。！？.!?；;])\s*([•\-*]\s+)/g, '$1\n$2')
    .replace(/\s+•\s+/g, '\n• ');

  const sectionTitles = [
    '核心事实提取',
    '核心事实',
    '深度洞察',
    '洞察分析',
    '与说法的精确对比',
    '与说法的关系',
    '准确点',
    '偏差与限定',
    '事实依据',
    '结论判断',
    '限定条件',
    '风险提示',
    '综合判断',
  ];
  const titlePattern = sectionTitles.join('|');

  normalized = normalized
    .replace(new RegExp(`(?:^|\\n)\\s*\\d+[\\.．、]\\s*\\*\\*(${titlePattern})\\*\\*[：:]\\s*`, 'g'), '\n### $1\n')
    .replace(new RegExp(`(?:^|\\n)\\s*\\d+[\\.．、]\\s*(${titlePattern})[：:]\\s*`, 'g'), '\n### $1\n')
    .replace(new RegExp(`(?:^|\\n)\\s*(?:[-•*]\\s+)?\\*\\*(${titlePattern})\\*\\*[：:]\\s*`, 'g'), '\n### $1\n')
    // 处理没有冒号的加粗标题（独占一行或紧跟内容）
    .replace(new RegExp(`(?:^|\\n)\\s*\\*\\*(${titlePattern})\\*\\*\\s*(?=\\n|\\*\\*|[^*]|$)`, 'g'), '\n### $1\n');

  return normalized
    .split('\n')
    .map(line => line.trimEnd())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

// ==================== 提取推理过程摘要（从第3节证据关系分析） ====================
function extractReasoningBrief(text) {
  if (!text) return '';

  // 策略1：提取第3节（证据关系分析）的内容
  const section3Match = text.match(/###\s*3[\.、]\s*.*?(?:证据关系|关系分析).*?\n+([\s\S]+?)(?=###\s*[45][\.、]|$)/i);
  if (section3Match) {
    let content = section3Match[1].trim();
    // 清理markdown但保留文字
    content = content.replace(/\*\*/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    content = content.replace(/^#{1,4}\s+/gm, '').replace(/^[•\-\*]\s+/gm, '');
    // 取前350字
    if (content.length > 350) {
      const cut = content.lastIndexOf('。', 350);
      content = cut > 200 ? content.substring(0, cut + 1) : content.substring(0, 347) + '...';
    }
    if (content.length > 20) return content;
  }

  // 策略2：提取第4节（不确定性与局限）
  const section4Match = text.match(/###\s*4[\.、]\s*.*?(?:不确定|局限).*?\n+([\s\S]+?)(?=###\s*5[\.、]|$)/i);
  if (section4Match) {
    let content = section4Match[1].trim();
    content = content.replace(/\*\*/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    if (content.length > 350) {
      const cut = content.lastIndexOf('。', 350);
      content = cut > 150 ? content.substring(0, cut + 1) : content.substring(0, 347) + '...';
    }
    if (content.length > 20) return content;
  }

  // 策略3：降级到提取第1节中的分析摘要（跳过结构化证据行）
  const lines = text.split('\n');
  const analysisLines = [];
  for (const line of lines) {
    const trimmed = line.trim();
    // 跳过标题、证据格式行、空行
    if (!trimmed || trimmed.match(/^#{1,4}\s/) || trimmed.match(/^\*\*证据\s*\[/)) continue;
    if (trimmed.match(/^###\s*5/) || trimmed.match(/^###\s*[45][\.、]/)) break;
    if (trimmed.length > 15) analysisLines.push(trimmed);
    if (analysisLines.length >= 3) break;
  }
  if (analysisLines.length > 0) {
    let result = analysisLines.join(' ').replace(/\*\*/g, '');
    if (result.length > 350) result = result.substring(0, 347) + '...';
    return result;
  }

  return '';
}

function buildEvidenceRelationLead(ec) {
  const supportCount = ec?.supporting_evidence?.length || 0;
  const opposeCount = ec?.opposing_evidence?.length || 0;
  const neutralCount = ec?.neutral_evidence?.length || 0;
  const total = supportCount + opposeCount + neutralCount;
  if (!total) return '';

  if (supportCount === total) {
    return `所有${total}条核心证据均支持该说法。`;
  }
  if (opposeCount === total) {
    return `所有${total}条核心证据均反对该说法。`;
  }
  if (opposeCount === 0 && supportCount > 0) {
    return `${total}条核心证据整体指向同一结论，其中部分证据提供限定或背景。`;
  }
  if (supportCount === 0 && opposeCount > 0) {
    return `${total}条核心证据整体反对该说法，其中部分证据提供限定或背景。`;
  }
  if (supportCount > opposeCount) {
    return `${total}条核心证据以支持为主，但存在反对或中性信息需要一并审阅。`;
  }
  if (opposeCount > supportCount) {
    return `${total}条核心证据以反对为主，但存在支持或中性信息需要一并审阅。`;
  }
  return `${total}条核心证据呈现多种立场，需要结合证据关系综合判断。`;
}

function normalizeReasoningEvidenceCountText(text, ec) {
  if (!text) return '';
  const supportCount = ec?.supporting_evidence?.length || 0;
  const opposeCount = ec?.opposing_evidence?.length || 0;
  const neutralCount = ec?.neutral_evidence?.length || 0;
  const total = supportCount + opposeCount + neutralCount;
  if (!total) return text;

  return String(text)
    .replace(
      /(?<!第)(?:(所有|全部|上述|以上|这些|这|本次|展示的)\s*)?\d+\s*(条|个)\s*(核心)?证据/g,
      (_, prefix = '', unit, qualifier = '') => {
        const normalizedQualifier = qualifier || '核心';
        return `${prefix || ''}${total}${unit}${normalizedQualifier}证据`;
      },
    )
    .replace(
      /(所有|全部|上述|以上|这些|这|本次|展示的)\s*证据/g,
      (_, prefix) => `${prefix}${total}条核心证据`,
    );
}

function buildReasoningBrief(text, ec) {
  const lead = buildEvidenceRelationLead(ec);
  const detail = normalizeReasoningEvidenceCountText(extractReasoningBrief(text), ec);
  if (lead && detail) return `${lead}${detail}`;
  return lead || detail || '';
}

function buildReasoningDisplayContent(text, ec) {
  if (!text) return '';

  let content = normalizeMarkdownLineBreaks(text);
  content = content.replace(
    /###\s*1[\.．、\s]*.*?证据立场分析[\s\S]*?(?=\n###\s*\d+[\.．、\s]|$)/i,
    ''
  );
  content = content.replace(/###\s*5[\.．、][\s\S]*$/i, '');
  content = normalizeReasoningDisplayHeadings(content);
  content = normalizeReasoningEvidenceCountText(content, ec);
  content = content.replace(/\n{3,}/g, '\n\n').trim();

  return content || normalizeReasoningEvidenceCountText(extractReasoningBrief(text), ec);
}

function normalizeReasoningDisplayHeadings(text) {
  if (!text) return '';

  return String(text).replace(
    /^(#{2,4})\s*\d+\s*[\.．、]\s*(关键引用|综合判断|证据关系分析|不确定性与局限|不确定性|局限|引用|证据关系|关系分析)(.*)$/gm,
    (_, hashes, title, suffix) => `${hashes} ${title}${suffix || ''}`
  );
}

// ==================== 简单提取：从文本中提取第一段（用于深度思考过程） ====================
function extractFirstParagraph(text, maxLength = 150) {
  if (!text) return '暂无内容';

  console.log('🔍 开始简单提取第一段，文本长度:', text.length);

  // 按段落分割
  const paragraphs = text.split(/\n\n+/).filter(p => p.trim());

  // 查找第一个非标题、非列表的段落
  let firstParagraph = '';
  for (const para of paragraphs) {
    const trimmed = para.trim();
    // 跳过标题（#开头）、列表（*或-开头）、空段落
    if (!trimmed.match(/^#+\s/) &&
        !trimmed.match(/^[\*\-]\s/) &&
        !trimmed.match(/^\d+\.\s/) &&
        trimmed.length > 20) {
      firstParagraph = trimmed;
      break;
    }
  }

  // 如果没找到，使用第一段
  if (!firstParagraph && paragraphs.length > 0) {
    firstParagraph = paragraphs[0].trim();
  }

  if (!firstParagraph) {
    return '暂无内容';
  }

  // 清理Markdown符号
  firstParagraph = firstParagraph
    .replace(/^#+\s+/gm, '')
    .replace(/\*\*/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^>\s+/gm, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\*\s+/gm, '')
    .replace(/^\-\s+/gm, '')
    .trim();

  // 截取到第一个句号
  if (firstParagraph.length > maxLength) {
    for (let i = maxLength; i >= maxLength * 0.5; i--) {
      if ('。！？.!?'.includes(firstParagraph[i])) {
        return firstParagraph.substring(0, i + 1);
      }
    }
    return firstParagraph.substring(0, maxLength - 3) + '...';
  }

  console.log('✅ 简单提取完成，长度:', firstParagraph.length);
  return firstParagraph;
}

// ==================== 从文本中智能提取简短摘要 ====================
function extractBriefSummary(text, maxLength = 300) { // 🔥 v0.5.5 增加maxLength从200→300
  if (!text) return '暂无内容';

  console.log('🔍 开始提取简短摘要，文本长度:', text.length);
  console.log('📄 文本前500字符:', text.substring(0, 500));

  // 🎯 方案3：组合提取（立场统计 + 证据关系分析）

  // 1. 提取"### 1. 证据立场分析"部分，统计立场分布
  // 🔥 v0.5.4 修复：支持全角句号．（快速模式的reasoning使用全角标点）
  // 🔥 v0.5.4 修复2：标题后只有一个换行符\n（而非\n\n）
  const stanceSectionRegex = /###\s*1[\.．、]\s*.*?证据立场分析\s*\n([\s\S]+?)(?=\n###|$)/;
  const stanceMatch = text.match(stanceSectionRegex);
  console.log('🔍 证据立场分析正则匹配结果:', stanceMatch ? '匹配成功' : '匹配失败');
  if (!stanceMatch) {
    console.log('⚠️ 未找到"### 1. 证据立场分析"部分');
    console.log('📄 文本中是否包含"证据立场分析"?', text.includes('证据立场分析'));
  }

  let stanceSummary = '';
  if (stanceMatch && stanceMatch[1]) {
    console.log('✅ 匹配到证据立场分析部分');
    const stanceContent = stanceMatch[1];
    console.log('📄 证据立场分析内容（前200字符）:', stanceContent.substring(0, 200));

    // 🔥 v0.5.5 修复：支持多种立场标记格式
    // 格式1: **立场**：**支持**
    // 格式2: 立场：**支持**
    // 格式3: **立场**: **支持**
    const supportMatches = stanceContent.match(/(?:\*\*立场\*\*[：:]\s*\*\*|立场[：:]\s*\*\*)支持\*\*/g);
    const opposeMatches = stanceContent.match(/(?:\*\*立场\*\*[：:]\s*\*\*|立场[：:]\s*\*\*)反对\*\*/g);
    const neutralMatches = stanceContent.match(/(?:\*\*立场\*\*[：:]\s*\*\*|立场[：:]\s*\*\*)中性\*\*/g);

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

  // 2. 提取"### 3. 证据关系分析"的核心结论（适度简化）
  // 🔥 v0.5.4 修复：支持全角句号．（快速模式的reasoning使用全角标点）
  // 🔥 v0.5.4 修复2：标题后只有一个换行符\n（而非\n\n）
  // 🔥 v0.5.5 优化2：保留完整关系描述，只去掉证据编号和冗余细节
  const relationshipSectionRegex = /###\s*3[\.．、]\s*.*?证据关系分析\s*\n([\s\S]+?)(?=\n###|$)/;
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

    // 🔥 v0.5.5 优化3：提取第一句完整描述，彻底简化
    const lines = relationshipContent.split(/\n/).filter(line => line.trim().length > 15);
    if (lines.length > 0) {
      let firstLine = lines[0].trim();

      // 🔥 彻底清理证据编号和冗余内容
      firstLine = firstLine
        .replace(/证据\[\d+(?:[，、]\s*\[\d+\])*?\]/g, '部分证据') // 替换证据编号列表
        .replace(/证据\[\d+\][：:]\s*/g, '') // 删除单个证据编号前缀
        .replace(/、\s*\[\d+\]/g, '等') // 替换"、 [7]"为"等"
        .replace(/\[\\d+\]/g, '') // 删除残留的单独编号
        .replace(/\([^)]*url[^)]*\)/gi, '') // 删除包含URL的括号
        .replace(/https?:\/\/[^\s]+/g, '') // 删除URL
        .replace(/\([^)]*\)/g, '') // 删除其他括号内容
        .trim();

      // 🔥 智能截取：保留120字符，截取到完整句子
      if (firstLine.length > 120) {
        // 优先寻找句号
        for (let i = 120; i >= 60; i--) {
          if ('。！？.!?'.includes(firstLine[i])) {
            firstLine = firstLine.substring(0, i + 1);
            break;
          }
        }
        // 如果没找到句号，寻找最后一个逗号
        if (firstLine.length > 120) {
          for (let i = 120; i >= 60; i--) {
            if ('，,；;'.includes(firstLine[i])) {
              firstLine = firstLine.substring(0, i + 1);
              break;
            }
          }
        }
        // 如果还是太长，直接截取
        if (firstLine.length > 120) {
          firstLine = firstLine.substring(0, 117) + '...';
        }
      }

      relationshipSummary = firstLine;
      console.log('📄 提取的关系描述（120字符）:', relationshipSummary);
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

// ==================== 行内Markdown渲染（先占位再转义）====================
function renderInlineMarkdown(text) {
  if (!text) return '';

  let result = text;
  const linkTokens = createMarkdownLinkTokenStore();

  // 1. 用占位符替换Markdown语法，避免被escapeHtml破坏
  result = result.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, linkText, url) => {
    return linkTokens.add(displayTextForMarkdownLink(linkText), url);
  });

  // 1b. 将裸露的URL转换为文本锚点（提取域名作为显示文本）
  result = result.replace(/https?:\/\/[^\s<>"{}|\\^`§]+/g, (url) => {
    const cleanUrl = normalizeMarkdownUrl(url.replace(/[)\].!?！？]+$/g, ''));
    try {
      const hostname = new URL(cleanUrl).hostname.replace(/^www\./, '');
      return linkTokens.add(hostname, cleanUrl);
    } catch (e) {
      return url;
    }
  });
  result = result.replace(/\*\*([^*]+)\*\*/g, '§§BOLD§§$1§§/BOLD§§');
  result = result.replace(/\*([^*]+)\*/g, '§§EM§§$1§§/EM§§');
  result = result.replace(/`([^`]+)`/g, '§§CODE§§$1§§/CODE§§');

  // 2. 转义HTML（占位符中的特殊字符也会被转义，后续统一恢复）
  result = escapeHtml(result);

  // 3. 恢复占位符为HTML标签
  result = result
    .replace(/§§BOLD§§/g, '<strong class="md-strong">')
    .replace(/§§\/BOLD§§/g, '</strong>')
    .replace(/§§EM§§/g, '<em class="md-em">')
    .replace(/§§\/EM§§/g, '</em>')
    .replace(/§§CODE§§/g, '<code class="md-code">')
    .replace(/§§\/CODE§§/g, '</code>');

  return linkEvidenceReferences(decorateMarkdownFields(linkTokens.restore(result)));
}

function decorateMarkdownFields(html) {
  if (!html) return '';

  const stanceClass = {
    '支持': 'support',
    '反对': 'oppose',
    '中性': 'neutral',
  };

  return html
    .replace(
      /(?:<strong class="md-strong">)?立场(?:<\/strong>)?([：:]\s*)(?:<strong class="md-strong">)?(支持|反对|中性)(?:<\/strong>)?/g,
      (_, separator, stance) => `<span class="md-field-label">立场</span>${separator}<span class="stance-tag stance-${stanceClass[stance]}">${stance}</span>`,
    )
    .replace(
      /(?:<strong class="md-strong">)?(来源|分析)(?:<\/strong>)?([：:])/g,
      '<span class="md-field-label">$1</span>$2',
    );
}

function createEvidenceAnchorLink(index) {
  const numericIndex = Number(index);
  if (!Number.isInteger(numericIndex) || numericIndex < 1 || numericIndex > 99) {
    return escapeHtml(String(index || ''));
  }
  return `<a href="#evidence-${numericIndex}" class="evidence-anchor-link" title="跳转到证据 ${numericIndex}">${numericIndex}</a>`;
}

function linkEvidenceReferences(html) {
  if (!html) return '';
  return html.replace(
    /证据\s*((?:\[?\s*\d{1,2}\s*\]?\s*(?:[-—至到、,，和及与]\s*)?)+)/g,
    (match, sequence) => {
      const linkedSequence = sequence.replace(
        /\[?\s*(\d{1,2})\s*\]?/g,
        (_, index) => createEvidenceAnchorLink(index),
      );
      return `证据 ${linkedSequence}`;
    },
  );
}

function getActiveResultTab(resultRoot) {
  return resultRoot?.querySelector('.tab-item.tab-active')?.dataset.tab || 'evidence';
}

function activateResultTab(resultRoot, tabName) {
  if (!resultRoot || !tabName) return;

  const targetTab = resultRoot.querySelector(`.tab-item[data-tab="${tabName}"]`);
  const targetPanel = resultRoot.querySelector(`#tab-${tabName}`);
  if (!targetTab || !targetPanel) return;

  resultRoot.querySelectorAll('.tab-item').forEach(tab => tab.classList.remove('tab-active'));
  targetTab.classList.add('tab-active');
  resultRoot.querySelectorAll('.tab-content').forEach(content => {
    content.style.display = content.id === `tab-${tabName}` ? 'block' : 'none';
  });
}

function getEvidenceScrollContainer() {
  return document.querySelector('#ai-check-window .ai-check-window-body');
}

function handleEvidenceAnchorClick(event) {
  const link = event.target?.closest?.('a.evidence-anchor-link');
  if (!link) return;

  const evidenceId = (link.getAttribute('href') || '').replace(/^#/, '');
  if (!evidenceId) return;

  const resultRoot = link.closest('#aiCheckResult') || document.getElementById('aiCheckResult');
  const target = document.getElementById(evidenceId);
  if (!target || !resultRoot?.contains(target)) return;

  event.preventDefault();

  const scrollContainer = getEvidenceScrollContainer();
  const returnState = {
    tab: getActiveResultTab(resultRoot),
    scrollTop: scrollContainer?.scrollTop || 0,
    link,
  };

  activateResultTab(resultRoot, 'evidence');

  if (scrollContainer) {
    const containerRect = scrollContainer.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const offset = targetRect.top - containerRect.top + scrollContainer.scrollTop - 16;
    scrollContainer.scrollTo({ top: Math.max(0, offset), behavior: 'smooth' });
  } else {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  target.classList.remove('evidence-card-jump');
  void target.offsetWidth;
  target.classList.add('evidence-card-jump');
  setTimeout(() => target.classList.remove('evidence-card-jump'), 1400);
  showEvidenceReturnButton(target, resultRoot, returnState);
}

function showEvidenceReturnButton(target, resultRoot, returnState) {
  resultRoot?.querySelectorAll('.evidence-return-link').forEach(button => button.remove());
  if (!target || !resultRoot || !returnState) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'evidence-return-link';
  button.textContent = '返回引用位置';
  button.addEventListener('click', () => {
    const scrollContainer = getEvidenceScrollContainer();
    activateResultTab(resultRoot, returnState.tab);

    requestAnimationFrame(() => {
      if (scrollContainer) {
        scrollContainer.scrollTo({ top: returnState.scrollTop, behavior: 'smooth' });
      }
      returnState.link?.classList?.add('evidence-anchor-return-focus');
      setTimeout(() => returnState.link?.classList?.remove('evidence-anchor-return-focus'), 1200);
      button.remove();
    });
  });

  target.appendChild(button);
}

function getMarkdownRelationClass(text) {
  const normalized = String(text || '').replace(/\s+/g, '');
  if (!normalized) return '';

  // 明确的正向结论：说法相符/属实/未歪曲等结论性表态优先识别，
  // 避免段落里出现"核心矛盾"这类名词性词汇就被误判为证据冲突。
  const hasPositiveVerdict = /(基本相符|完全相符|大致相符|高度相符|相互吻合|相互印证|与[一-龥A-Za-z0-9]{0,12}(?:基本|完全|大致|高度)?一致|与[一-龥A-Za-z0-9]{0,12}(?:基本|完全|大致|高度)?吻合|与[一-龥A-Za-z0-9]{0,12}(?:基本|完全|大致|高度)?相符|未(?:见|存在)?(?:歪曲|夸大|失实|偏差)|属实|说法(?:基本)?成立|核心事实(?:基本)?(?:成立|属实)|准确概括)/.test(normalized);
  if (hasPositiveVerdict) {
    return ' md-relation md-relation-support';
  }

  const hasNegatedConflict = /(无|没有|未见|不存在|并无|并未|未发现|无任何)(?:[一-龥]{0,16})?(质疑|矛盾|冲突|对立|反对|反驳|不一致|分歧)/.test(normalized);
  const hasSupportSignal = /(支持|印证|证实|佐证|一致|吻合|相符|共同指向|相互补充|补充说明|证据链)/.test(normalized);
  if (!hasNegatedConflict && /(矛盾|冲突|对立|反对|反驳|不一致|否定|存疑|分歧)/.test(normalized)) {
    return ' md-relation md-relation-conflict';
  }
  if (hasSupportSignal) {
    return ' md-relation md-relation-support';
  }
  return '';
}

// ==================== 解析Markdown到HTML ====================
function parseMarkdown(markdown) {
  if (!markdown) return '';

  markdown = normalizeMarkdownLineBreaks(markdown);
  const lines = markdown.split('\n');
  let html = '';
  let inList = false;
  let listType = 'ul';
  let listHtml = '';
  let paragraphBuffer = [];

  function flushParagraph() {
    const paragraphText = paragraphBuffer.join('\n').trim();
    if (paragraphText) {
      const paragraphHtml = paragraphBuffer
        .map((line) => renderInlineMarkdown(line))
        .join('<br>');
      html += `<p class="md-p${getMarkdownRelationClass(paragraphText)}">${paragraphHtml}</p>`;
      paragraphBuffer = [];
    }
  }

  function flushList() {
    if (inList) {
      const tag = listType === 'ol' ? 'ol' : 'ul';
      html += `<${tag} class="md-${tag}">${listHtml}</${tag}>`;
      listHtml = '';
      inList = false;
      listType = 'ul';
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // 空行：结束当前列表和段落
    if (line.trim() === '') {
      flushList();
      flushParagraph();
      continue;
    }

    // 标题
    const h4Match = line.match(/^####\s+(.*)/);
    const h3Match = line.match(/^###\s+(.*)/);
    const h2Match = line.match(/^##\s+(.*)/);
    if (h4Match || h3Match || h2Match) {
      flushList();
      flushParagraph();
      const match = h4Match || h3Match || h2Match;
      const tag = h4Match ? 'h4' : (h3Match ? 'h3' : 'h2');
      html += `<${tag} class="md-${tag}">${renderInlineMarkdown(match[1])}</${tag}>`;
      continue;
    }

    // 列表项（支持 - * • 和 1. / 1、）
    const liMatch = line.match(/^\s*([\-*•])\s+(.*)/);
    const orderedLiMatch = line.match(/^\s*(\d+)[\.．、]\s+(.*)/);
    if (liMatch) {
      flushParagraph();
      if (inList && listType !== 'ul') flushList();
      inList = true;
      listType = 'ul';
      listHtml += `<li class="md-li${getMarkdownRelationClass(liMatch[2])}">${renderInlineMarkdown(liMatch[2])}</li>`;
      continue;
    }
    if (orderedLiMatch) {
      flushParagraph();
      if (inList && listType !== 'ol') flushList();
      inList = true;
      listType = 'ol';
      listHtml += `<li class="md-li${getMarkdownRelationClass(orderedLiMatch[2])}">${renderInlineMarkdown(orderedLiMatch[2])}</li>`;
      continue;
    }

    // 非列表行：结束当前列表
    if (inList) {
      flushList();
    }

    // 引用块
    const bqMatch = line.match(/^>\s+(.*)/);
    if (bqMatch) {
      flushParagraph();
      html += `<blockquote class="md-blockquote">${renderInlineMarkdown(bqMatch[1])}</blockquote>`;
      continue;
    }

    // 普通文本行：累积到段落缓冲，连续行用真实 <br> 连接
    paragraphBuffer.push(line);
  }

  // 处理末尾未闭合的内容
  flushList();
  flushParagraph();

  return `<div class="markdown-content">${html}</div>`;
}

// ==================== 核查建议生成 ====================
function generateSuggestions(data) {
  const suggestions = [];
  const ec = data.evidence_chain;
  if (!ec) return suggestions;

  const supportCount = ec.supporting_evidence?.length || 0;
  const opposeCount = ec.opposing_evidence?.length || 0;
  const neutralCount = ec.neutral_evidence?.length || 0;
  const total = supportCount + opposeCount + neutralCount;

  if (total <= 2) {
    suggestions.push('证据较少，建议尝试换一种表述方式重新核查，或补充更具体的时间、地点等细节');
  }
  if (supportCount > 0 && opposeCount > 0) {
    suggestions.push('存在支持与反对的证据分歧，建议关注不同信息源的角度差异，综合判断');
  }
  if (neutralCount >= total * 0.6) {
    suggestions.push('大部分证据为中性参考，无法直接验证或反驳该说法，建议寻找更权威的信息源');
  }

  suggestions.push('以上核查结果仅供参考，涉及重要决策时请咨询权威机构或专业渠道');

  return suggestions;
}

// ==================== 创建证据卡片HTML ====================
function createEvidenceCardHTML(evidence, type = 'neutral', index = 0, displayIndex = index + 1) {
  const url = evidence.url || '#';
  const title = evidence.title || '无标题';
  const summary = evidence.content?.summary || evidence.content?.key_quote || '';
  const domain = evidence.domain || (url !== '#' ? (() => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch(e) { return ''; } })() : '');
  const publishDate = evidence.validation?.publish_date || evidence.publish_date || '';
  const evidenceIndex = Math.max(1, Number(displayIndex) || index + 1);

  // 立场标签
  const stanceLabels = { support: '支持', oppose: '反对', neutral: '参考' };
  const stanceLabel = stanceLabels[type] || '参考';

  let sourceLine = '';
  if (domain) sourceLine += escapeHtml(domain);
  if (domain && publishDate) sourceLine += ' · ';
  if (publishDate) sourceLine += escapeHtml(publishDate);

  const mainContent = renderInlineMarkdown(summary.slice(0, 200));
  const mainLabel = '内容摘要';

  return `
    <div class="evidence-card" id="evidence-${evidenceIndex}" data-evidence-type="${type}" data-evidence-index="${evidenceIndex}">
      <div class="evidence-card-header">
        <span class="evidence-index">证据 ${evidenceIndex}</span>
        <span class="evidence-stance-badge stance-${type}">${stanceLabel}</span>
        <div class="evidence-title" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
      </div>
      ${sourceLine ? `<div class="evidence-source">${sourceLine}</div>` : ''}
      <div class="evidence-analysis-wrap">
        <div class="evidence-analysis-label">${mainLabel}</div>
        <div class="evidence-analysis">${mainContent}</div>
      </div>
      ${url !== '#' ? (
        evidence.validation?.link_status === '不可访问'
          ? `<span class="evidence-link evidence-link-broken" title="该链接已失效或无法访问">⚠️ 链接已失效</span>`
          : `<a href="${url}" target="_blank" class="evidence-link">查看原文 →</a>`
      ) : ''}
    </div>
  `;
}

// ==================== 切换section展开/收起（全局函数） ====================
window.toggleSection = function(sectionId, iconId) {
  console.log('🔄 切换section:', sectionId, iconId);
  const section = document.getElementById(sectionId);
  const icon = document.getElementById(iconId);
  const toggleBtn = icon?.parentElement; // 🔥 v0.5.5 获取toggle按钮

  if (section && icon) {
    const isCollapsed = section.classList.contains('collapsed');
    section.classList.toggle('collapsed');

    // 🔥 v0.5.5 添加aria-expanded属性，支持CSS旋转动画
    if (toggleBtn) {
      toggleBtn.setAttribute('aria-expanded', isCollapsed ? 'true' : 'false');
    }

    // 🔥 v0.5.5 保留原有的箭头符号更新（作为fallback）
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

function formatFetchError(error) {
  const message = error?.message || String(error || '');
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return `无法连接核查后端：${API_BASE}。请确认后端服务可访问、网络未阻断，并检查扩展已重新加载。`;
  }
  if (/abort/i.test(message)) {
    return '核查请求已取消';
  }
  return message || '核查失败，请检查后端服务是否启动';
}

// ==================== HTML转义 ====================
function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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


// ==================== 侧边栏功能 ====================

let sidebarVisible = false;
let currentCheckResult = null; // 保存当前核查结果，用于收起到侧边栏
let currentCheckClaim = null;

// 侧边栏迷你进度条（独立容器，不受 renderHistoryList 影响）
function showSidebarMiniProgress(claim) {
  const container = document.getElementById('sidebarMiniProgressContainer');
  if (!container) return;
  window._aiCheckSidebarDone = false;

  const progressItem = document.createElement('div');
  progressItem.id = 'sidebarMiniProgress';
  progressItem.className = 'history-item sidebar-progress-item';
  progressItem.innerHTML = `
    <div class="history-item-header">
      <span class="history-item-verdict sidebar-progress-status">核查中...</span>
      <span class="sidebar-progress-open">点击展开</span>
    </div>
    <div class="history-item-claim">${escapeHtml(claim.length > 30 ? claim.substring(0,30)+'...' : claim)}</div>
    <div class="sidebar-progress-track">
      <div id="sidebarMiniProgressFill" class="sidebar-progress-fill"></div>
    </div>
    <div class="history-item-time" id="sidebarMiniProgressText">正在核查...</div>
  `;

  progressItem.addEventListener('click', () => {
    reopenCheckFromSidebar(claim);
  });

  container.innerHTML = '';
  container.appendChild(progressItem);
}

function reopenCheckFromSidebar(claim) {
  // 取消收起状态，恢复流式输出到模态窗口
  window._aiCheckCollapsed = false;
  window._aiCheckCollapsedBeforeDone = false;

  // 关闭侧边栏
  toggleSidebar(false);

  // 重新打开模态窗口
  openCheckWindow(claim);

  // 恢复流式进度到新模态窗口
  setTimeout(() => {
    const stream = window._aiCheckStream;
    if (!stream) return;

    const startBtn = document.getElementById('aiCheckStart');
    const progressBar = document.getElementById('aiCheckProgress');
    const thinkingEl = document.getElementById('aiCheckThinking');

    const hasAccumulated = stream.streamStarted && (stream.thinkingContent || stream.fullContent);

    if (stream.running) {
      // 流仍在跑：隐藏开始按钮，显示进度条
      if (startBtn) startBtn.classList.add('hidden');
      if (progressBar) progressBar.classList.remove('hidden');
    }

    // 恢复已累积的流式内容（不论流是否还活着，有内容就展示）
    if (hasAccumulated) {
      if (thinkingEl) {
        thinkingEl.classList.remove('hidden');
        const content = stream.fullContent || stream.thinkingContent;
        const header = stream.fullContent
          ? '正在生成核查报告...'
          : stream.running
            ? '正在分析证据相关性...'
            : '核查已中断，以下是已生成内容';
        thinkingEl.innerHTML = `<div class="streaming-card streaming-card--draft">
          <div class="streaming-card-header">
            <span>${header}</span>
            <small>最终以正式报告为准</small>
          </div>
          <div class="streaming-card-body">${simpleMarkdownRender(content)}<span class="streaming-card-scroll-anchor"></span></div>
        </div>`;
        scrollStreamingDraftToBottom(thinkingEl);
      }
    }
  }, 100);
}

function updateSidebarMiniProgress(percent, message) {
  if (window._aiCheckSidebarDone || document.querySelector('.sidebar-progress-item-done')) {
    return;
  }

  let fill = document.getElementById('sidebarMiniProgressFill');
  let text = document.getElementById('sidebarMiniProgressText');
  // 如果DOM元素丢失，重新创建
  if (!fill || !text) {
    const container = document.getElementById('sidebarMiniProgressContainer');
    if (!container) return;
    const claim = window._aiCheckCollapsedClaim || '';
    showSidebarMiniProgress(claim);
    fill = document.getElementById('sidebarMiniProgressFill');
    text = document.getElementById('sidebarMiniProgressText');
  }
  if (fill) fill.style.width = percent;
  if (text) text.textContent = message;
}

function clearSidebarProgressTimer() {
  if (window._sidebarProgressTimer) {
    clearInterval(window._sidebarProgressTimer);
    window._sidebarProgressTimer = null;
  }
}

function collapseCompletedResultToSidebar(claim, resultData) {
  clearSidebarProgressTimer();
  window._aiCheckCollapsed = false;
  window._aiCheckCollapsedBeforeDone = false;
  window._aiCheckCollapsedClaim = '';
  window._aiCheckSidebarDone = false;
  window._aiCheckSetProgress = null;
  removeSidebarMiniProgress();
  closeCheckWindow();
  toggleSidebar(true);
  if (resultData && !resultData.__historySaved) {
    saveToHistory(claim, resultData);
  }
}

function completeSidebarCheck(claim, resultData) {
  clearSidebarProgressTimer();
  window._aiCheckCollapsedBeforeDone = false;
  window._aiCheckCollapsedClaim = '';
  window._aiCheckCollapsed = false;
  window._aiCheckSidebarDone = true;
  currentCheckResult = resultData;
  currentCheckClaim = claim;
  showSidebarCompletionNotice(claim, resultData);
  if (resultData && !resultData.__historySaved) {
    saveToHistory(claim, resultData);
  }
  showToast('核查完成，点击历史中的完成提示查看结果');
}

function showSidebarCompletionNotice(claim, resultData) {
  const container = document.getElementById('sidebarMiniProgressContainer');
  if (!container) return;

  const verdict = resultData?.evidence_chain?.conclusion || resultData?.verdict || '完成';
  const progressItem = document.createElement('div');
  progressItem.id = 'sidebarMiniProgress';
  progressItem.className = 'history-item sidebar-progress-item sidebar-progress-item-done';
  progressItem.innerHTML = `
    <div class="sidebar-completion-banner">
      <span class="sidebar-completion-dot"></span>
      <span><strong>核查完成</strong> 结果已生成</span>
    </div>
    <div class="history-item-header">
      <span class="history-item-verdict sidebar-progress-status sidebar-progress-status-done">核查完成</span>
      <span class="sidebar-progress-open sidebar-progress-open-done">查看完整报告</span>
    </div>
    <div class="history-item-claim">${escapeHtml(claim.length > 42 ? claim.substring(0,42)+'...' : claim)}</div>
    <div class="sidebar-progress-track sidebar-progress-track-done">
      <div id="sidebarMiniProgressFill" class="sidebar-progress-fill sidebar-progress-fill-done"></div>
    </div>
    <div class="history-item-time" id="sidebarMiniProgressText">${escapeHtml(verdict)}</div>
  `;

  progressItem.addEventListener('click', () => {
    openCheckWindow(claim);
    setTimeout(() => {
      const startBtn = document.getElementById('aiCheckStart');
      const progressEl = document.getElementById('aiCheckProgress');
      const loadingEl = document.getElementById('aiCheckLoading');
      const thinkingEl = document.getElementById('aiCheckThinking');
      const resultEl = document.getElementById('aiCheckResult');

      if (startBtn) startBtn.classList.add('hidden');
      if (progressEl) progressEl.classList.add('hidden');
      if (loadingEl) loadingEl.classList.add('hidden');
      if (thinkingEl) thinkingEl.classList.add('hidden');
      if (resultEl) {
        resultEl.classList.remove('hidden');
        displayResult(resultData, claim);
      }
      toggleSidebar(false);
      removeSidebarMiniProgress();
    }, 100);
  });

  container.innerHTML = '';
  container.appendChild(progressItem);
}

function removeSidebarMiniProgress() {
  const container = document.getElementById('sidebarMiniProgressContainer');
  if (container) container.innerHTML = '';
}

function createSidebar() {
  // 如果已存在侧边栏，先移除（可能处于closing动画中）
  const existing = document.getElementById('ai-check-sidebar');
  if (existing) existing.remove();

  const sidebar = document.createElement('div');
  sidebar.id = 'ai-check-sidebar';
  sidebar.className = 'ai-check-sidebar';
  sidebar.innerHTML = `
    <div class="ai-check-sidebar-header">
      <h3>核查历史</h3>
      <button class="ai-check-sidebar-close" title="关闭">x</button>
    </div>
    <div class="ai-check-sidebar-body">
      <button class="sidebar-new-check-btn" id="sidebarNewCheckBtn">新建核查</button>
      <div id="sidebarMiniProgressContainer"></div>
      <div id="sidebarHistoryList"></div>
    </div>
    <div class="ai-check-sidebar-footer">
      <button class="sidebar-clear-btn" id="sidebarClearBtn">清空历史</button>
    </div>
  `;
  document.body.appendChild(sidebar);

  // 绑定关闭按钮
  sidebar.querySelector('.ai-check-sidebar-close').addEventListener('click', () => {
    toggleSidebar(false);
  });

  // 绑定新建核查
  sidebar.querySelector('#sidebarNewCheckBtn').addEventListener('click', () => {
    const text = getSelectedText();
    if (text) {
      openCheckWindow(text);
    } else {
      showToast('请先选中要核查的文字');
    }
  });

  // 绑定清空历史
  sidebar.querySelector('#sidebarClearBtn').addEventListener('click', () => {
    if (confirm('确定要清空所有核查历史吗？')) {
      chrome.storage.local.set({ factcheck_history: [] }, () => {
        renderHistoryList([]);
        updateSidebarToggle();
      });
    }
  });

  // 加载历史记录
  loadHistory().then(items => {
    renderHistoryList(items);
  });

  sidebarVisible = true;
}

function toggleSidebar(show) {
  if (show) {
    createSidebar();
    const existing = document.getElementById('ai-check-sidebar');
    if (existing && existing.classList.contains('closing')) {
      existing.classList.remove('closing');
    }
    sidebarVisible = true;
  } else {
    const sidebar = document.getElementById('ai-check-sidebar');
    if (sidebar) {
      sidebar.classList.add('closing');
      sidebar.addEventListener('animationend', () => {
        sidebar.remove();
        sidebarVisible = false;
      }, { once: true });
    }
    sidebarVisible = false;
  }
  updateSidebarToggle();
}

function createSidebarToggle() {
  // 扩展 reload 后旧 toggle 可能仍在 DOM 中，但点击事件已经失效。
  document.getElementById('ai-check-sidebar-toggle')?.remove();

  const toggle = document.createElement('div');
  toggle.id = 'ai-check-sidebar-toggle';
  toggle.className = 'ai-check-sidebar-toggle';
  toggle.innerHTML = '📋<span class="badge hidden">0</span>';
  toggle.title = '核查历史';
  document.body.appendChild(toggle);

  toggle.addEventListener('click', () => {
    toggleSidebar(!sidebarVisible);
  });

  updateSidebarToggle();
}

function updateSidebarToggle() {
  const toggle = document.getElementById('ai-check-sidebar-toggle');
  if (!toggle) return;

  // 侧边栏打开时隐藏 toggle
  if (sidebarVisible) {
    toggle.style.display = 'none';
  } else {
    toggle.style.display = 'flex';
    loadHistory().then(items => {
      const badge = toggle.querySelector('.badge');
      if (items.length > 0) {
        badge.classList.remove('hidden');
        badge.textContent = items.length > 99 ? '99+' : items.length;
      } else {
        badge.classList.add('hidden');
      }
    });
  }
}

// 时间格式化
function formatTimeAgo(timestamp) {
  const now = Date.now();
  const diff = now - timestamp;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 7) return `${days}天前`;
  const date = new Date(timestamp);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function renderHistoryList(items) {
  const list = document.getElementById('sidebarHistoryList');
  if (!list) return;

  if (!items || items.length === 0) {
    list.innerHTML = '<div class="sidebar-empty"><span class="sidebar-empty-icon">📋</span>暂无核查历史<br>选中文本后点击核查按钮开始</div>';
  } else {
    const now = Date.now();
    list.innerHTML = items.map(item => {
    const verdictClass = item.verdict === '属实' ? 'verdict-true' :
                         item.verdict === '不实' ? 'verdict-false' : 'verdict-uncertain';
    const verdictIcon = item.verdict === '属实' ? '✅' :
                        item.verdict === '不实' ? '❌' : '⚠️';
    const claimShort = item.claim.length > 30 ? item.claim.substring(0, 30) + '...' : item.claim;
    const isNew = now - item.timestamp < 30000;
    const newBadge = isNew ? '<span class="history-item-new-badge">刚刚</span>' : '';
    return `
      <div class="history-item ${verdictClass}${isNew ? ' history-item-new' : ''}" data-history-id="${item.id}">
        <button class="history-item-delete" data-delete-id="${item.id}" title="删除">x</button>
        <div class="history-item-header">
          <span class="history-item-verdict ${verdictClass}">${verdictIcon} ${item.verdict}</span>
          ${newBadge}
        </div>
        <div class="history-item-claim">${escapeHtml(claimShort)}</div>
        <div class="history-item-time">${formatTimeAgo(item.timestamp)}</div>
      </div>
    `;
  }).join('');
  }

  // 绑定点击事件：打开历史详情
  list.querySelectorAll('.history-item[data-history-id]').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('history-item-delete')) return;
      const id = el.dataset.historyId;
      openHistoryDetail(id);
    });
  });

  // 绑定删除按钮
  list.querySelectorAll('.history-item-delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.dataset.deleteId;
      deleteHistoryItem(id);
    });
  });
}

function openHistoryDetail(historyId) {
  loadHistory().then(items => {
    const item = items.find(i => i.id === historyId);
    if (!item || !item.result) {
      showToast('历史记录数据丢失');
      return;
    }
    if (item.result && typeof item.result === 'object') {
      item.result.__historySaved = true;
      item.result.__historyId = item.id;
    }
    // 关闭侧边栏，打开模态窗口展示历史结果
    toggleSidebar(false);
    openCheckWindow(item.claim);

    // 等模态窗口渲染后，直接展示结果
    setTimeout(() => {
      const startBtn = document.getElementById('aiCheckStart');
      const progressEl = document.getElementById('aiCheckProgress');
      const loadingEl = document.getElementById('aiCheckLoading');
      const thinkingEl = document.getElementById('aiCheckThinking');
      const resultEl = document.getElementById('aiCheckResult');

      if (startBtn) startBtn.classList.add('hidden');
      if (progressEl) progressEl.classList.add('hidden');
      if (loadingEl) loadingEl.classList.add('hidden');
      if (thinkingEl) thinkingEl.classList.add('hidden');
      if (resultEl) {
        resultEl.classList.remove('hidden');
        currentCheckResult = item.result;
        currentCheckClaim = item.claim;
        displayResult(item.result, item.claim);
      }
    }, 100);
  });
}

function deleteHistoryItem(id) {
  loadHistory().then(items => {
    const filtered = items.filter(i => i.id !== id);
    chrome.storage.local.set({ factcheck_history: filtered }, () => {
      renderHistoryList(filtered);
      updateSidebarToggle();
    });
  });
}

function pruneHistoryResultForStorage(result) {
  if (!result || typeof result !== 'object') return result;
  const pruned = JSON.parse(JSON.stringify(result));
  if (pruned.thinking_process && pruned.thinking_process.length > 2000) {
    pruned.thinking_process = pruned.thinking_process.slice(0, 2000) + '...';
  }
  if (pruned.reasoning && pruned.reasoning.length > 12000) {
    pruned.reasoning = pruned.reasoning.slice(0, 12000) + '...';
  }
  if (pruned.evidence_chain?.ai_summary && pruned.evidence_chain.ai_summary.length > 8000) {
    pruned.evidence_chain.ai_summary = pruned.evidence_chain.ai_summary.slice(0, 8000) + '...';
  }
  return pruned;
}

function pruneHistoryForStorage(items, limit = 30) {
  return items.slice(0, limit).map((item) => ({
    ...item,
    result: pruneHistoryResultForStorage(item.result)
  }));
}

function renderSavedHistory(items) {
  const list = document.getElementById('sidebarHistoryList');
  if (list) {
    renderHistoryList(items);
  }
  updateSidebarToggle();

  // 移除完成通知，避免和历史列表重复显示同一核查
  const doneNotice = document.querySelector('.sidebar-progress-item-done');
  if (doneNotice) {
    doneNotice.remove();
  }
}

function saveToHistory(claim, result) {
  const verdict = result.evidence_chain?.conclusion || result.verdict || '无法判断';
  const id = `${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
  if (result && typeof result === 'object') {
    result.__historySaved = true;
    result.__historyId = id;
  }

  const historyItem = {
    id,
    claim,
    verdict,
    timestamp: Date.now(),
    pageUrl: window.location.href,
    pageTitle: document.title,
    result
  };

  loadHistory().then(items => {
    items.unshift(historyItem);
    const prunedItems = pruneHistoryForStorage(items);

    chrome.storage.local.set({ factcheck_history: prunedItems }, () => {
      if (chrome.runtime?.lastError) {
        console.warn('保存核查历史失败，尝试减少历史数量:', chrome.runtime.lastError.message);
        const compactItems = pruneHistoryForStorage(items, 10);
        chrome.storage.local.set({ factcheck_history: compactItems }, () => {
          if (chrome.runtime?.lastError) {
            console.error('保存核查历史失败:', chrome.runtime.lastError.message);
            showToast('核查完成，但历史记录空间不足，未能保存');
            return;
          }
          renderSavedHistory(compactItems);
        });
        return;
      }
      renderSavedHistory(prunedItems);
    });
  });
}

function loadHistory() {
  return new Promise((resolve) => {
    if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
      chrome.storage.local.get(['factcheck_history'], (result) => {
        resolve(result.factcheck_history || []);
      });
    } else {
      resolve([]);
    }
  });
}


// ==================== 页面加载完成后创建按钮 ====================
function ensurePersistentControls() {
  if (!document.body) return;

  if (!document.getElementById('ai-check-float-btn')) {
    createFloatingButton();
  }

  if (!document.getElementById('ai-check-sidebar-toggle') && !document.getElementById('ai-check-sidebar')) {
    createSidebarToggle();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', ensurePersistentControls);
} else {
  ensurePersistentControls();
}

if (window.addEventListener) {
  window.addEventListener('pageshow', ensurePersistentControls);
  window.addEventListener('focus', ensurePersistentControls);
}
document.addEventListener('visibilitychange', ensurePersistentControls);
if (typeof setInterval === 'function') {
  const persistentControlsTimer = setInterval(ensurePersistentControls, 2000);
  if (persistentControlsTimer?.unref) persistentControlsTimer.unref();
}

// ==================== 监听来自Popup的消息 ====================
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log('收到消息:', request);

  if (request.action === 'ping') {
    sendResponse({ ok: true });
    return true;
  }

  // 处理获取选中文字的请求
  if (request.action === 'getSelection') {
    const selectedText = getSelectedText();
    console.log('返回选中的文字:', selectedText);
    sendResponse({ text: selectedText });
  }

  return true;
});

// ==================== 多窗口历史记录同步 ====================
// 当其他窗口保存历史记录时，自动刷新当前窗口的侧边栏
if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.onChanged) {
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== 'local') return;
    if (!changes.factcheck_history) return;

    const newItems = changes.factcheck_history.newValue || [];

    // 刷新侧边栏历史列表（如果侧边栏当前可见）
    const sidebar = document.getElementById('ai-check-sidebar');
    if (sidebar) {
      renderHistoryList(newItems);
    }

    // 更新侧边栏 toggle badge
    updateSidebarToggle();
  });
}

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

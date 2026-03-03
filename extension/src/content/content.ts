// 内容脚本 - 注入到网页中
// 负责处理UI交互和通信

import { createResultPanel } from '../components/ResultPanel';
import { createLoadingIndicator } from '../components/LoadingIndicator';
import { createMessageToast } from '../components/MessageToast';

// 全局变量
let resultPanel: HTMLElement | null = null;
let currentSelection: string = '';

// 初始化内容脚本
function initContentScript() {
  console.log('事实核查内容脚本已加载');

  // 监听来自background的消息
  chrome.runtime.onMessage.addListener(handleMessage);
}

// 处理来自background的消息
function handleMessage(message: any, sender: chrome.runtime.MessageSender, sendResponse: (response?: any) => void) {
  switch (message.type) {
    case 'SHOW_LOADING':
      showLoadingIndicator(message.payload.text);
      break;

    case 'SHOW_RESULT':
      showResultPanel(message.payload);
      break;

    case 'SHOW_ERROR':
      showErrorToast(message.payload.message);
      break;

    case 'SHOW_MESSAGE':
      showMessageToast(message.payload.message);
      break;

    default:
      console.warn('未知的消息类型:', message.type);
  }
}

// 显示加载指示器
function showLoadingIndicator(text: string) {
  removeExistingPanel();

  currentSelection = text;
  const loadingEl = createLoadingIndicator();
  document.body.appendChild(loadingEl);

  // 定位加载指示器到选中文本附近
  positionElementNearSelection(loadingEl);
}

// 显示核查结果面板
function showResultPanel(result: any) {
  removeExistingPanel();

  const panel = createResultPanel(currentSelection, result);
  document.body.appendChild(panel);

  // 定位面板到合适位置
  positionElementNearSelection(panel);

  // 添加事件监听器
  addPanelEventListeners(panel, result);
}

// 显示错误提示
function showErrorToast(message: string) {
  removeExistingPanel();
  const toast = createMessageToast(message, 'error');
  document.body.appendChild(toast);
  positionElementNearSelection(toast);

  // 3秒后自动移除
  setTimeout(() => toast.remove(), 3000);
}

// 显示普通消息
function showMessageToast(message: string) {
  const toast = createMessageToast(message, 'info');
  document.body.appendChild(toast);
  positionElementNearSelection(toast);

  // 2秒后自动移除
  setTimeout(() => toast.remove(), 2000);
}

// 移除现有面板
function removeExistingPanel() {
  const existingPanel = document.getElementById('fact-check-panel');
  const existingLoading = document.getElementById('fact-check-loading');
  const existingToast = document.getElementById('fact-check-toast');

  existingPanel?.remove();
  existingLoading?.remove();
  existingToast?.remove();
}

// 在选中文本附近定位元素
function positionElementNearSelection(element: HTMLElement) {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) {
    // 如果没有选中，居中显示
    positionInCenter(element);
    return;
  }

  const range = selection.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  // 计算元素位置
  let left = rect.left + window.scrollX;
  let top = rect.bottom + window.scrollY + 10;

  // 确保不超出视窗右边界
  if (left + element.offsetWidth > viewportWidth) {
    left = Math.max(10, viewportWidth - element.offsetWidth - 20);
  }

  // 确保不超出视窗底部
  if (top + element.offsetHeight > viewportHeight + window.scrollY) {
    top = Math.max(10, rect.top + window.scrollY - element.offsetHeight - 10);
  }

  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
}

// 居中显示元素
function positionInCenter(element: HTMLElement) {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  element.style.left = `${(viewportWidth - element.offsetWidth) / 2}px`;
  element.style.top = `${(viewportHeight - element.offsetHeight) / 2}px`;
}

// 添加面板事件监听器
function addPanelEventListeners(panel: HTMLElement, result: any) {
  // 关闭按钮
  const closeBtn = panel.querySelector('.close-btn');
  closeBtn?.addEventListener('click', () => panel.remove());

  // 复制证据链接按钮
  const copyBtn = panel.querySelector('.copy-btn');
  copyBtn?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(result.source_url);
      copyBtn.textContent = '已复制！';
      setTimeout(() => {
        copyBtn.textContent = '复制链接';
      }, 2000);
    } catch (error) {
      console.error('复制失败:', error);
    }
  });

  // 举报按钮
  const reportBtn = panel.querySelector('.report-btn');
  reportBtn?.addEventListener('click', () => {
    window.open('https://www.12377.cn/', '_blank');
  });

  // 分享按钮
  const shareBtn = panel.querySelector('.share-btn');
  shareBtn?.addEventListener('click', () => {
    shareResult(result);
  });

  // 点击面板外部关闭
  document.addEventListener('click', function closePanel(e: MouseEvent) {
    if (!panel.contains(e.target as Node)) {
      panel.remove();
      document.removeEventListener('click', closePanel);
    }
  });
}

// 分享核查结果
function shareResult(result: any) {
  const shareText = `事实核查结果：${result.verdict}\n\n证据：${result.evidence_quote}\n来源：${result.source_url}`;

  if (navigator.share) {
    navigator.share({
      title: '事实核查结果',
      text: shareText
    }).catch(console.error);
  } else {
    // 如果不支持Web Share API，复制到剪贴板
    navigator.clipboard.writeText(shareText).then(() => {
      alert('核查结果已复制到剪贴板');
    }).catch(() => {
      alert('分享失败，请手动复制');
    });
  }
}

// 监听滚动事件，重新定位面板
window.addEventListener('scroll', () => {
  const panel = document.getElementById('fact-check-panel');
  if (panel) {
    const rect = panel.getBoundingClientRect();
    if (rect.top < 0 || rect.bottom > window.innerHeight) {
      panel.remove();
    }
  }
});

// 监听窗口大小变化
window.addEventListener('resize', () => {
  const panel = document.getElementById('fact-check-panel');
  if (panel) {
    positionElementNearSelection(panel);
  }
});

// 初始化
initContentScript();

export {};
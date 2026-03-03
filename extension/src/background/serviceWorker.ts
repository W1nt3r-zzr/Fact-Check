// Chrome插件后台服务脚本
// 负责处理插件的核心逻辑和API调用

import type { FactCheckRequest, FactCheckResponse } from '../types/api';

// 插件安装时初始化
chrome.runtime.onInstalled.addListener(() => {
  console.log('事实核查AI助手已安装');

  // 创建右键菜单
  chrome.contextMenus.create({
    id: 'factCheck',
    title: '核查此内容',
    contexts: ['selection']
  });
});

// 处理右键菜单点击
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'factCheck' && info.selectionText) {
    const selectedText = info.selectionText.trim();
    if (selectedText) {
      await checkSelectedText(selectedText, tab.id!);
    }
  }
});

// 处理插件图标点击
chrome.action.onClicked.addListener(async (tab) => {
  // 获取当前选中的文本
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id! },
    function: getSelectedText
  });

  const selectedText = results[0].result;
  if (selectedText) {
    await checkSelectedText(selectedText, tab.id!);
  } else {
    // 如果没有选中文本，提示用户
    chrome.tabs.sendMessage(tab.id!, {
      type: 'SHOW_MESSAGE',
      payload: {
        message: '请先选中要核查的文本'
      }
    });
  }
});

// 从页面获取选中文本
function getSelectedText(): string {
  const selection = window.getSelection();
  return selection ? selection.toString().trim() : '';
}

// 核查选中文本
async function checkSelectedText(selectedText: string, tabId: number) {
  try {
    // 显示加载状态
    chrome.tabs.sendMessage(tabId, {
      type: 'SHOW_LOADING',
      payload: { text: selectedText }
    });

    // 调用后端API进行核查
    const result = await callFactCheckAPI(selectedText);

    // 发送结果到内容脚本
    chrome.tabs.sendMessage(tabId, {
      type: 'SHOW_RESULT',
      payload: result
    });

  } catch (error) {
    console.error('核查失败:', error);
    chrome.tabs.sendMessage(tabId, {
      type: 'SHOW_ERROR',
      payload: {
        message: '核查失败，请稍后重试'
      }
    });
  }
}

// 调用事实核查API
async function callFactCheckAPI(text: string): Promise<FactCheckResponse> {
  const API_BASE_URL = 'http://localhost:8000/api/v1/check';

  const request: FactCheckRequest = {
    claim: text,
    timestamp: Date.now(),
    source_url: window.location.href
  };

  const response = await fetch(API_BASE_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request)
  });

  if (!response.ok) {
    throw new Error(`API请求失败: ${response.status}`);
  }

  return response.json();
}

// 监听来自content script的消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case 'CHECK_TEXT':
      checkSelectedText(message.payload.text, sender.tab?.id!)
        .then(sendResponse)
        .catch(error => {
          console.error('处理消息失败:', error);
          sendResponse({ error: error.message });
        });
      return true; // 保持消息通道开放

    default:
      console.warn('未知的消息类型:', message.type);
  }
});

export {};
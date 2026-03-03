// API接口类型定义

export interface FactCheckRequest {
  /** 待核查的文本内容 */
  claim: string;
  /** 时间戳 */
  timestamp: number;
  /** 来源页面URL */
  source_url?: string;
}

export interface FactCheckResponse {
  /** 核查结论 */
  verdict: 'Supports' | 'Refutes' | 'NotEnoughInfo';
  /** 证据引用原文 */
  evidence_quote: string;
  /** 证据来源URL */
  source_url: string;
  /** 搜索关键词 */
  search_keywords: string;
  /** 不确定性说明 */
  uncertainty_note?: string;
  /** 社会影响提示 */
  social_impact?: string;
  /** 处理时间（毫秒） */
  processing_time: number;
  /** API版本 */
  api_version: string;
}

export interface APIError {
  error: string;
  message: string;
  details?: any;
}

export interface SearchQuery {
  query: string;
  sites?: string[];
  count?: number;
}

export interface SearchResult {
  title: string;
  snippet: string;
  url: string;
  date?: string;
  domain: string;
}

export interface ChatMessage {
  type: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
}
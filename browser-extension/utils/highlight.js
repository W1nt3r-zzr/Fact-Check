// ==================== Highlight Utilities ====================

(function(global) {
  function escapeHtmlLocal(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeHighlights(summary, highlights) {
    if (!summary || !Array.isArray(highlights)) return [];

    return highlights
      .map((highlight) => {
        const start = Number(highlight.start_index);
        const end = Number(highlight.end_index);
        if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start) {
          return null;
        }
        if (end > summary.length) {
          return null;
        }
        const text = summary.slice(start, end);
        if (!text) {
          return null;
        }
        return {
          text,
          start,
          end,
          type: highlight.type || 'neutral',
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start))
      .filter((highlight, index, arr) => {
        if (index === 0) return true;
        const prev = arr[index - 1];
        return highlight.start >= prev.end;
      });
  }

  function buildEvidenceSummaryHtml(summary, highlights, options = {}) {
    if (!summary) return '无摘要';

    const normalizedHighlights = normalizeHighlights(summary, highlights);
    const maxLength = options.maxLength || 180;

    // 从开头截取固定长度，作为原文的整体预览
    // 区别于围绕高亮截取的"重点片段"，摘要展示的是原文全貌的开头部分
    const end = Math.min(summary.length, maxLength);
    const snippetText = summary.slice(0, end);

    // 只渲染落在截取范围内的高亮
    const visibleHighlights = normalizedHighlights
      .filter((highlight) => highlight.end > 0 && highlight.start < end)
      .map((highlight) => ({
        start: Math.max(highlight.start, 0),
        end: Math.min(highlight.end, end),
        type: highlight.type,
      }));

    let html = '';
    let cursor = 0;

    visibleHighlights.forEach((highlight) => {
      if (highlight.start > cursor) {
        html += escapeHtmlLocal(snippetText.slice(cursor, highlight.start));
      }
      html += `<mark class="evidence-highlight evidence-highlight--${escapeHtmlLocal(highlight.type)}">${escapeHtmlLocal(snippetText.slice(highlight.start, highlight.end))}</mark>`;
      cursor = highlight.end;
    });

    if (cursor < snippetText.length) {
      html += escapeHtmlLocal(snippetText.slice(cursor));
    }

    if (!visibleHighlights.length) {
      html = escapeHtmlLocal(snippetText);
    }

    if (end < summary.length) {
      html = `${html}…`;
    }

    return html;
  }

  function findSentenceWindow(summary, highlight, options = {}) {
    const maxLength = options.maxLength || 140;
    const punctuation = new Set(['。', '！', '？', '；', '.', '!', '?', ';', '\n']);
    let start = 0;
    let end = summary.length;

    for (let i = highlight.start - 1; i >= 0; i -= 1) {
      if (punctuation.has(summary[i])) {
        start = i + 1;
        break;
      }
    }

    for (let i = highlight.end; i < summary.length; i += 1) {
      if (punctuation.has(summary[i])) {
        end = i + 1;
        break;
      }
    }

    while (start < end && /\s/.test(summary[start])) start += 1;
    while (end > start && /\s/.test(summary[end - 1])) end -= 1;

    if (end - start <= maxLength) {
      return { start, end };
    }

    const contextLength = Math.max(18, Math.floor((maxLength - (highlight.end - highlight.start)) / 2));
    start = Math.max(start, highlight.start - contextLength);
    end = Math.min(end, highlight.end + contextLength);

    if (end - start > maxLength) {
      end = Math.min(summary.length, start + maxLength);
    }

    return { start, end };
  }

  function renderHighlightedSnippet(summary, snippet, highlights) {
    const snippetText = summary.slice(snippet.start, snippet.end);
    const visibleHighlights = highlights
      .filter((highlight) => highlight.end > snippet.start && highlight.start < snippet.end)
      .map((highlight) => ({
        start: Math.max(highlight.start, snippet.start) - snippet.start,
        end: Math.min(highlight.end, snippet.end) - snippet.start,
        type: highlight.type,
      }));

    let html = '';
    let cursor = 0;

    visibleHighlights.forEach((highlight) => {
      if (highlight.start > cursor) {
        html += escapeHtmlLocal(snippetText.slice(cursor, highlight.start));
      }
      html += `<mark class="evidence-highlight evidence-highlight--${escapeHtmlLocal(highlight.type)}">${escapeHtmlLocal(snippetText.slice(highlight.start, highlight.end))}</mark>`;
      cursor = highlight.end;
    });

    if (cursor < snippetText.length) {
      html += escapeHtmlLocal(snippetText.slice(cursor));
    }

    if (!visibleHighlights.length) {
      html = escapeHtmlLocal(snippetText);
    }

    if (snippet.start > 0) html = `…${html}`;
    if (snippet.end < summary.length) html = `${html}…`;
    return html;
  }

  function buildEvidenceFocusHtml(summary, highlights, options = {}) {
    if (!summary) return '';

    const normalizedHighlights = normalizeHighlights(summary, highlights);
    if (!normalizedHighlights.length) return '';

    const maxSnippets = options.maxSnippets || 2;
    const focusSnippets = [];

    normalizedHighlights.forEach((highlight) => {
      if (focusSnippets.length >= maxSnippets) return;

      const snippet = findSentenceWindow(summary, highlight, options);
      const overlapsExisting = focusSnippets.some((existing) => (
        snippet.start < existing.end && snippet.end > existing.start
      ));

      if (!overlapsExisting) {
        focusSnippets.push(snippet);
      }
    });

    if (!focusSnippets.length) return '';

    const hasMultipleSnippets = focusSnippets.length > 1;
    const snippetHtml = focusSnippets.map((snippet, index) => {
      const label = hasMultipleSnippets ? `重点片段 ${index + 1}` : '重点片段';
      return [
        '<div class="evidence-focus-item">',
        `<div class="evidence-focus-label">${label}</div>`,
        `<div class="evidence-focus-text">${renderHighlightedSnippet(summary, snippet, normalizedHighlights)}</div>`,
        '</div>',
      ].join('');
    }).join('');

    return [
      '<div class="evidence-focus">',
      snippetHtml,
      '</div>',
    ].join('');
  }

  global.buildEvidenceSummaryHtml = buildEvidenceSummaryHtml;
  global.buildEvidenceFocusHtml = buildEvidenceFocusHtml;
  global.normalizeEvidenceHighlights = normalizeHighlights;

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
      buildEvidenceFocusHtml,
      buildEvidenceSummaryHtml,
      normalizeEvidenceHighlights: normalizeHighlights,
    };
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);

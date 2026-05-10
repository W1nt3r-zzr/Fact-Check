// ==================== Shared Markdown Utilities ====================

function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function simpleMarkdownRender(text) {
  const linkTokens = createMarkdownLinkTokenStore();
  const html = normalizeMarkdownLineBreaks(text)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, linkText, url) => (
      linkTokens.add(displayTextForMarkdownLink(linkText), url)
    ))
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
    add(linkText, url) {
      const cleanUrl = normalizeMarkdownUrl(url);
      if (!/^https?:\/\//i.test(cleanUrl)) {
        return escapeHtml(linkText || cleanUrl || '');
      }

      const displayText = linkText || cleanUrl;
      const token = `§§LINK_${links.length}§§`;
      links.push({ text: displayText, url: cleanUrl });
      return token;
    },
    restore(html) {
      return html.replace(/§§LINK_(\d+)§§/g, (match, index) => {
        const link = links[Number(index)];
        if (!link) return '';
        return `<a href="${escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer" class="markdown-link">${escapeHtml(link.text)}</a>`;
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

function renderInlineMarkdown(text) {
  if (!text) return '';

  let result = text;
  const linkTokens = createMarkdownLinkTokenStore();

  result = result.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, linkText, url) => (
    linkTokens.add(displayTextForMarkdownLink(linkText), url)
  ));
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
  result = escapeHtml(result);

  result = result
    .replace(/§§BOLD§§/g, '<strong class="md-strong">')
    .replace(/§§\/BOLD§§/g, '</strong>')
    .replace(/§§EM§§/g, '<em class="md-em">')
    .replace(/§§\/EM§§/g, '</em>')
    .replace(/§§CODE§§/g, '<code class="md-code">')
    .replace(/§§\/CODE§§/g, '</code>');

  return decorateMarkdownFields(linkTokens.restore(result));
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

function getMarkdownRelationClass(text) {
  const normalized = String(text || '').replace(/\s+/g, '');
  if (!normalized) return '';
  const hasNegatedConflict = /(无|没有|未见|不存在|并无|并未|未发现|无任何)(?:[一-龥]{0,6})?(矛盾|冲突|对立|反对|反驳|不一致|分歧)/.test(normalized);
  const hasSupportSignal = /(支持|印证|证实|佐证|一致|吻合|共同指向|相互补充|补充说明|证据链)/.test(normalized);
  if (!hasNegatedConflict && /(矛盾|冲突|对立|反对|反驳|不一致|否定|存疑|分歧)/.test(normalized)) {
    return ' md-relation md-relation-conflict';
  }
  if (hasSupportSignal) {
    return ' md-relation md-relation-support';
  }
  return '';
}

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

  lines.forEach((line) => {
    if (line.trim() === '') {
      flushList();
      flushParagraph();
      return;
    }

    const h4Match = line.match(/^####\s+(.*)/);
    const h3Match = line.match(/^###\s+(.*)/);
    const h2Match = line.match(/^##\s+(.*)/);
    if (h4Match || h3Match || h2Match) {
      flushList();
      flushParagraph();
      const match = h4Match || h3Match || h2Match;
      const tag = h4Match ? 'h4' : (h3Match ? 'h3' : 'h2');
      html += `<${tag} class="md-${tag}">${renderInlineMarkdown(match[1])}</${tag}>`;
      return;
    }

    const liMatch = line.match(/^\s*([\-*•])\s+(.*)/);
    const orderedLiMatch = line.match(/^\s*(\d+)[\.．、]\s+(.*)/);
    if (liMatch || orderedLiMatch) {
      flushParagraph();
      const nextType = orderedLiMatch ? 'ol' : 'ul';
      if (inList && listType !== nextType) flushList();
      inList = true;
      listType = nextType;
      const itemText = (orderedLiMatch || liMatch)[2];
      listHtml += `<li class="md-li${getMarkdownRelationClass(itemText)}">${renderInlineMarkdown(itemText)}</li>`;
      return;
    }

    if (inList) flushList();

    const bqMatch = line.match(/^>\s+(.*)/);
    if (bqMatch) {
      flushParagraph();
      html += `<blockquote class="md-blockquote">${renderInlineMarkdown(bqMatch[1])}</blockquote>`;
      return;
    }

    paragraphBuffer.push(line);
  });

  flushList();
  flushParagraph();

  return `<div class="markdown-content">${html}</div>`;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { escapeHtml, simpleMarkdownRender, parseMarkdown, renderInlineMarkdown, normalizeMarkdownLineBreaks, decorateMarkdownFields, getMarkdownRelationClass };
}

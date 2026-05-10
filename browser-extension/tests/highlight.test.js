const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildEvidenceSummaryHtml,
  buildEvidenceFocusHtml,
} = require('../utils/highlight.js');

test('buildEvidenceSummaryHtml renders backend highlight ranges with escaped html', () => {
  const summary = '浏览器插件会请求 http://127.0.0.1:8000/api/v1/check 获取结果。';
  const html = buildEvidenceSummaryHtml(summary, [
    {
      text: 'http://127.0.0.1:8000',
      start_index: 9,
      end_index: 30,
      type: 'support',
    },
  ], { maxLength: 120 });

  assert.match(html, /evidence-highlight evidence-highlight--support/);
  assert.match(html, /http:\/\/127\.0\.0\.1:8000/);
  assert.doesNotMatch(html, /<script>/);
});

test('buildEvidenceSummaryHtml slices from beginning and truncates with ellipsis', () => {
  const summary = '前置信息前置信息前置信息前置信息前置信息，实际连接地址为 127.0.0.1:8000，随后继续描述更多细节和补充背景。';
  const html = buildEvidenceSummaryHtml(summary, [], { maxLength: 36 });

  // 新逻辑：从开头截取，不以 … 开头，超出长度时以 … 结尾
  assert.doesNotMatch(html, /^…/);
  assert.match(html, /…$/);
  assert.match(html, /前置信息/);
});

test('buildEvidenceFocusHtml promotes the sentence containing the key highlight', () => {
  const summary = '第一句只是背景信息。第二句明确说明插件默认请求 http://127.0.0.1:8000/api/v1/check 获取核查结果。第三句是补充说明。';
  const start = summary.indexOf('http://127.0.0.1:8000');
  const html = buildEvidenceFocusHtml(summary, [
    {
      text: 'http://127.0.0.1:8000',
      start_index: start,
      end_index: start + 'http://127.0.0.1:8000'.length,
      type: 'support',
    },
  ]);

  assert.match(html, /重点片段/);
  assert.doesNotMatch(html, /第一句只是背景信息/);
  assert.match(html, /第二句明确说明插件默认请求/);
  assert.match(html, /evidence-highlight--support/);
});

test('buildEvidenceFocusHtml renders multiple distinct focus snippets', () => {
  const summary = '公告显示少缴税款911.18万元。处理结果显示罚款1891.24万元。背景说明不应抢占重点。';
  const taxStart = summary.indexOf('911.18万元');
  const penaltyStart = summary.indexOf('1891.24万元');
  const html = buildEvidenceFocusHtml(summary, [
    {
      text: '911.18万元',
      start_index: taxStart,
      end_index: taxStart + '911.18万元'.length,
      type: 'support',
    },
    {
      text: '1891.24万元',
      start_index: penaltyStart,
      end_index: penaltyStart + '1891.24万元'.length,
      type: 'support',
    },
  ]);

  assert.match(html, /重点片段 1/);
  assert.match(html, /重点片段 2/);
  assert.match(html, /911\.18万元/);
  assert.match(html, /1891\.24万元/);
});

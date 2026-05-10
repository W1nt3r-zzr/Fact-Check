const test = require('node:test');
const assert = require('node:assert/strict');

const { parseMarkdown, simpleMarkdownRender } = require('../utils/markdown.js');

test('parseMarkdown renders numbered reasoning steps as ordered lists', () => {
  const html = parseMarkdown([
    '### 3. 证据关系分析',
    '1. 第一条证据提供时间线。',
    '2. 第二条证据补充来源可信度。',
  ].join('\n'));

  assert.match(html, /<h3 class="md-h3">3\. 证据关系分析<\/h3>/);
  assert.match(html, /<ol class="md-ol">/);
  assert.match(html, /第一条证据提供时间线/);
  assert.match(html, /第二条证据补充来源可信度/);
});

test('parseMarkdown renders indented bullet items as lists', () => {
  const html = parseMarkdown([
    '### 洞察分析',
    '   - 信息来源较集中。',
    '   - 时间线互相印证。',
  ].join('\n'));

  assert.match(html, /<ul class="md-ul">/);
  assert.match(html, /信息来源较集中/);
  assert.match(html, /时间线互相印证/);
});

test('parseMarkdown renders soft line breaks without showing literal br tags', () => {
  const html = parseMarkdown([
    '证据1：税务部门通报。',
    '证据2：媒体复核报道。',
  ].join('\n'));

  assert.match(html, /证据1：税务部门通报。<br>证据2：媒体复核报道。/);
  assert.doesNotMatch(html, /&lt;br&gt;/);
});

test('parseMarkdown treats backend br tags as line breaks', () => {
  const html = parseMarkdown('证据1：税务部门通报。<br>证据2：媒体复核报道。<br/>证据3：官方公告。');

  assert.match(html, /证据1：税务部门通报。<br>证据2：媒体复核报道。<br>证据3：官方公告。/);
  assert.doesNotMatch(html, /&lt;br/);
});

test('simpleMarkdownRender treats backend br tags as line breaks', () => {
  const html = simpleMarkdownRender('第一行<br>第二行');

  assert.equal(html, '第一行<br>第二行');
});

test('parseMarkdown renders evidence links without exposing anchor attributes', () => {
  const html = parseMarkdown('**证据 1 [国家税务总局](https://www.chinatax.gov.cn/example?id=1)** - 来源：官方');

  assert.match(html, /<a href="https:\/\/www\.chinatax\.gov\.cn\/example\?id=1" target="_blank" rel="noopener noreferrer" class="markdown-link">国家税务总局<\/a>/);
  assert.doesNotMatch(html, />[^<]*target=/);
});

test('parseMarkdown decorates stance and field labels in evidence analysis', () => {
  const html = parseMarkdown('**来源**：国家税务总局<br>**立场**：**支持**<br>**分析**：该来源直接证明核心事实。');

  assert.match(html, /<span class="md-field-label">来源<\/span>：国家税务总局/);
  assert.match(html, /<span class="md-field-label">立场<\/span>：<span class="stance-tag stance-support">支持<\/span>/);
  assert.match(html, /<span class="md-field-label">分析<\/span>：该来源直接证明核心事实。/);
});

test('parseMarkdown decorates opposing stance', () => {
  const html = parseMarkdown('立场：反对');

  assert.match(html, /<span class="stance-tag stance-oppose">反对<\/span>/);
});

test('parseMarkdown treats negated conflict wording as support', () => {
  const html = parseMarkdown(
    '所有10条核心证据中，除证据9（虎扑）讨论的是非法改装这一不相干话题外，其余所有的核心证据均高度一致地指向同一事件，核心事实在所有相关证据中完全吻合，无任何矛盾之处。',
  );

  assert.match(html, /md-relation-support/);
  assert.doesNotMatch(html, /md-relation-conflict/);
});

// ==================== Shared Utility Functions ====================

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`;
}

function extractKeywords(claim) {
  const words = claim.split(/[\s,，.。!！?？;；:：、]+/);
  const stopWords = ['的', '了', '是', '在', '和', '与', '或', '但', '而', '等', '很', '也', '都', '就', '这', '那', '有', '没有', '什么', '如何', '为什么'];
  return words
    .filter(word => word.length >= 2 && !stopWords.includes(word))
    .filter((word, index, self) => self.indexOf(word) === index)
    .slice(0, 10);
}

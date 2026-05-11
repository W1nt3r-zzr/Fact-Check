document.addEventListener('DOMContentLoaded', () => {
  const entry = document.getElementById('ai-check-newtab-entry');
  const claimText = document.getElementById('claimText');

  if (!entry || !claimText) return;

  entry.addEventListener('click', () => {
    claimText.scrollIntoView({ behavior: 'smooth', block: 'center' });
    claimText.focus();
    entry.classList.add('newtab-entry-pulse');
    setTimeout(() => entry.classList.remove('newtab-entry-pulse'), 450);
  });
});

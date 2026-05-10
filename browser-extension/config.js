// ==================== Shared Configuration ====================
// Switch environment by changing API_BASE here

const EXT_CONFIG = {
  // API_BASE: 'https://squatter-filled-could.ngrok-free.dev',   // ngrok 隧道
  API_BASE: 'https://fact-check-production-8d0f.up.railway.app', // Railway 云端
  // API_BASE: 'http://localhost:8000',                                // 本地开发
  VERSION: '2.0.0',
  UPDATE_CHECK: {
    enabled: true,
    repo: 'W1nt3r-zzr/Fact-Check'
  },
  CACHE_DURATION_DAYS: 7
};

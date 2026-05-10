# 云端部署与插件分发说明

本项目推荐使用“后端部署到云端，试用者只安装 Chrome 插件”的方式分发。

## 1. 部署后端到 Railway

1. 将项目推送到 GitHub 私有仓库。
2. 打开 Railway，创建 New Project，选择 Deploy from GitHub repo。
3. 选择本项目仓库。
4. 如果 Railway 要求选择服务根目录，设置为：

   ```text
   backend
   ```

5. 在 Railway 的 Variables 中添加：

   ```text
   LLM_API_KEY=你的 DeepSeek API Key
   LLM_BASE_URL=https://api.deepseek.com
   LLM_MODEL=deepseek-v4-pro
   BOCHA_API_KEY=你的 Bocha API Key
   TAVILY_API_KEY=你的 Tavily API Key
   MAX_CONCURRENT_CHECKS=2
   ```

   `MAX_CONCURRENT_CHECKS` 用于限制同时进入 DeepSeek 推理阶段的核查任务数量。超过该数量的插件请求会在后端排队，并在插件进度区显示当前运行数、排队数和本次请求的位置。该值应按 DeepSeek 账号实际并发额度和 Railway 实例规格调整。

6. 部署完成后，在 Railway 的 Networking 设置里 Generate Domain，得到类似：

   ```text
   https://your-service.up.railway.app
   ```

7. 打开这个地址的 `/health`，如果看到下面结果，说明后端可用：

   ```json
   {"status":"healthy"}
   ```

## 2. 配置插件连接云端后端

修改 `browser-extension/config.js`：

```js
const EXT_CONFIG = {
  API_BASE: 'https://your-service.up.railway.app',
  VERSION: '2.0.0',
  CACHE_DURATION_DAYS: 7
};
```

如果使用的不是 Railway 域名，还需要在 `browser-extension/manifest.json` 的 `host_permissions` 中加入你的后端域名，例如：

```json
"https://your-service.example.com/*"
```

## 3. 打包给试用者

压缩 `browser-extension` 文件夹，命名为：

```text
AI信息核查助手-试用版.zip
```

不要把 `backend/.env`、API Key 或整个后端源码发给普通试用者。

## 4. 发布到 GitHub Release 并提示用户更新

本项目插件采用“GitHub Release + 插件内更新提示”的方式分发。用户仍然需要手动下载新版压缩包并重新加载插件；Chrome 开发者模式安装的解压版插件不会从 GitHub 自动更新。

发布新版本时：

1. 同步更新版本号，`browser-extension/manifest.json` 和 `browser-extension/config.js` 中的版本必须一致，例如：

   ```text
   2.0.0
   ```

2. 确认 `browser-extension/config.js` 已配置 GitHub 仓库：

   ```js
   UPDATE_CHECK: {
     enabled: true,
     repo: 'W1nt3r-zzr/Fact-Check'
   }
   ```

3. 打包插件，ZIP 根目录必须直接包含 `manifest.json`：

   ```bash
   mkdir -p release
   cd browser-extension
   zip -r ../release/AI信息核查助手-v2.0.0.zip . -x "*.DS_Store" "tests/*"
   cd ..
   ```

4. 推送代码并创建 GitHub Release：

   ```bash
   git add browser-extension DEPLOYMENT.md
   git commit -m "Release browser extension v2.0.0"
   git tag v2.0.0
   git push Fact-Check main --tags

   gh release create v2.0.0 \
     release/AI信息核查助手-v2.0.0.zip \
     --repo W1nt3r-zzr/Fact-Check \
     --title "AI信息核查助手 v2.0.0" \
     --notes "发布说明写这里" \
     --latest
   ```

5. 当 GitHub 最新 Release 的版本号高于插件本地 `VERSION` 时，插件弹窗会显示“下载最新版”提示。用户下载后解压覆盖本地插件目录，再到 `chrome://extensions/` 点击插件卡片上的重新加载按钮。

## 5. 试用者安装说明

1. 解压 `AI信息核查助手-试用版.zip`。
2. 打开 Chrome，访问：

   ```text
   chrome://extensions/
   ```

3. 打开右上角“开发者模式”。
4. 点击“加载已解压的扩展程序”。
5. 选择解压后的 `browser-extension` 文件夹。
6. 打开任意网页，选中文字，点击插件开始核查。

## 6. 发布前检查

- `backend/config.py` 不应包含真实 API Key。
- Railway Variables 中必须配置真实 API Key。
- `browser-extension/config.js` 必须使用云端 HTTPS 地址，不能是 `http://localhost:8000`。
- `browser-extension/manifest.json` 必须允许访问该云端域名。
- `browser-extension/manifest.json` 和 `browser-extension/config.js` 的版本号必须一致。
- 在试用者电脑上安装前，先在自己的 Chrome 里用同一个压缩包测试一次。

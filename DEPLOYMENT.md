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
   ```

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

## 4. 试用者安装说明

1. 解压 `AI信息核查助手-试用版.zip`。
2. 打开 Chrome，访问：

   ```text
   chrome://extensions/
   ```

3. 打开右上角“开发者模式”。
4. 点击“加载已解压的扩展程序”。
5. 选择解压后的 `browser-extension` 文件夹。
6. 打开任意网页，选中文字，点击插件开始核查。

## 5. 发布前检查

- `backend/config.py` 不应包含真实 API Key。
- Railway Variables 中必须配置真实 API Key。
- `browser-extension/config.js` 必须使用云端 HTTPS 地址，不能是 `http://localhost:8000`。
- `browser-extension/manifest.json` 必须允许访问该云端域名。
- 在试用者电脑上安装前，先在自己的 Chrome 里用同一个压缩包测试一次。

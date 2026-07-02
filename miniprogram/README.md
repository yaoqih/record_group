# RecordFlow 微信小程序 MVP

## 运行

1. 在微信开发者工具中导入本目录 `miniprogram/`。
2. 项目已经在 `project.config.json` 中配置小程序 AppID。
3. 首次导入或更新依赖后，在微信开发者工具中执行 `工具 -> 构建 npm`。当前 UI 使用 TDesign 组件库，组件从 npm 构建产物加载。
4. 当前 MVP 使用根目录下的 `app.json`、`app.js`、`pages/` 和 `utils/`。微信开发者工具默认生成的 `miniprogram/` 子目录 TypeScript 模板没有参与这个 MVP。
5. 本地联调时启动后端：

```bash
uvicorn recordflow_agent.api:app --host 0.0.0.0 --port 8000
```

6. 后端配置微信登录：

```bash
export WECHAT_MINIAPP_APPID="你的小程序 AppID"
export WECHAT_MINIAPP_SECRET="你的小程序 AppSecret"
export RECORDFLOW_SESSION_SECRET="任意长随机字符串"
export RECORDFLOW_MINIAPP_SIGNUP_POINTS="10"
```

7. 如需真机或上线，把 `utils/config.js` 里的 `API_BASE` 改成 HTTPS 域名，并在微信公众平台配置 request/uploadFile/downloadFile 合法域名。

## 开发者工具游客模式

游客模式下 `wx.login` 返回模拟结果，不能完成真实微信登录。只想先调页面、上传和任务流时，可以临时把 `utils/config.js` 里的 `USE_DEV_LOGIN` 改成 `true`，后端会使用 `/site/auth/dev/login` 创建一个本地开发用户。

正式联调真实微信登录时：

- `USE_DEV_LOGIN` 必须改回 `false`
- `project.config.json` 必须填真实小程序 AppID
- 后端必须配置 `WECHAT_MINIAPP_APPID` 和 `WECHAT_MINIAPP_SECRET`

## 功能

- 微信登录并绑定后端 `site_users`
- 查看当前用户点数
- 上传音频/视频创建转写任务
- 查看任务列表和任务详情
- 确认开始转写
- 查看已完成任务的分句文本
- 悬浮播放器、点击分句跳转播放进度
- 导出 SRT、TXT、Word
- 微信支付充值点数
- 修改昵称、退出登录

# RecordFlow 管理端

该目录只构建 RecordFlow 管理端，不再提供浏览器用户测试页面。

开发时先启动 FastAPI，然后运行：

```bash
npm install
npm run dev
```

访问 `http://localhost:5173/admin`。直接访问 Vite 根路径会跳转到 `/admin`。

生产构建：

```bash
npm run build
```

FastAPI 会在 `/admin` 及其子路由提供 `dist` 中的管理端，并在 `/assets/*` 提供构建资源；服务根路径 `/` 保持 404。

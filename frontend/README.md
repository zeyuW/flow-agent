# Flow Agent Web 控制台

独立的 Flow Agent 管理控制台，提供运行总览、状态展示与实时更新基础能力。

## 本地开发

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

浏览器始终通过同源 `/api` 访问管理 API。Next.js 在服务端以
`ADMIN_API_BASE_URL` 代理请求，因此浏览器不会受到后端 CORS 限制。示例：

```bash
ADMIN_API_BASE_URL=http://127.0.0.1:8790
```

不要在 `.env.local`、前端代码或浏览器存储中保存 API key、Token、用户内容或其他密钥。`ADMIN_API_BASE_URL` 仅供 Next.js 服务端读取，不能以 `NEXT_PUBLIC_` 前缀暴露密钥。

## 检查与构建

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

## 实时数据

页面通过 `/api/traces`、`/api/traces/{trace_id}` 和 `/api/events` 获取 REST
快照，每 30 秒刷新一次。启动管理 API 后设置：

```bash
ADMIN_API_BASE_URL=http://127.0.0.1:8790
```

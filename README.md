# OCS AI Local

Python 3.12 的单人本地 AI 题库服务。通过 OCS 的自定义题库接口接入，无需修改、重新编译 OCS Desktop，也不需要 Cloudflare。

支持单选、多选、判断、填空、图像题；提供本地试搜页面、SQLite 答案缓存、耗时和 token 用量记录。模型配置由服务端 `.env` 管理，OCS 仅持有本地访问 Token。

## 启动（Windows / PowerShell）

在项目目录执行：

```powershell
./start.ps1
```

首次运行使用 `py -3.12` 创建 `.venv`、安装依赖，并从 `.env.example` 创建 `.env`，自动生成随机 `LOCAL_TOKEN`。已有 `.env` 不会被覆盖。首次创建后即使模型 Key 为空也能打开页面查看配置，但搜题会提示补充 Key。

打开 `.env` 填入自己的 `LLM_API_KEY`，保存后按 Ctrl+C 停止服务，再运行 `./start.ps1`。若系统策略阻止脚本运行，可直接使用下面的手动命令，无需修改系统执行策略。

```powershell
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-lock.txt
./.venv/Scripts/python.exe -m pip install -e . --no-deps
# 仅在没有 .env 时执行以下命令
./.venv/Scripts/python.exe -c "from pathlib import Path; import secrets; Path('.env').write_text(Path('.env.example').read_text(encoding='utf-8').replace('replace-with-a-random-token',secrets.token_urlsafe(32)),encoding='utf-8')"
./.venv/Scripts/python.exe run.py
```

访问 **http://127.0.0.1:8765**。使用完毕按 Ctrl+C 停止。服务始终仅监听 `127.0.0.1`，不支持通过 `.env` 改成公网监听。

## 接入 OCS

1. 本地页面点击「复制题库配置」，或打开 `http://127.0.0.1:8765/ocs-config.json` 手动复制完整 JSON。
2. 网课页面 OCS 悬浮窗 → 通用 → 全局设置 → 题库配置，粘贴并保存。如果已有题库，合并 JSON 数组中的对象，保留已有配置。
3. 确认 OCS 的「搜题最大耗时」大于本服务 `LLM_TIMEOUT_SECONDS`。默认服务总超时 110 秒，建议 OCS 设置为 120 秒或更高。旧版 OCS 的固定短超时可能需要更新脚本。
4. 先在本地页面试搜，再在 OCS 的练习搜题中验证。若浏览器提示本地网络访问权限，允许当前课程页面访问本机服务。使用题库配置中的 `GM_xmlhttpRequest`，并按 OCS/用户脚本管理器提示放行 `127.0.0.1` 请求。

配置只含 `${title}`、`${options}`、`${type}`；不需要向 OCS 填写模型 Key、模型名等信息。更改 `PORT` 或 `LOCAL_TOKEN` 后，需要重新复制 OCS 配置。

## `.env` 参数

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容 base URL，自动追加 `/chat/completions`；其他供应商可能需要 `/v1` |
| `LLM_API_KEY` | 空 | 模型服务 API Key |
| `LLM_MODEL` | `deepseek-flash` | DeepSeek 当前官方 V4.1 Flash API 名称；代理平台须使用其公布的模型标识 |
| `LLM_THINKING_MODE` | `enabled` | `enabled` / `disabled` / `omit`；`omit` 不发送 `thinking` 字段 |
| `LLM_REASONING_EFFORT` | `low` | 发送为 `reasoning_effort`，留空则不发送；关闭思考时不发送该字段 |
| `VISION_ENABLED` | `true` | 图片作为 `image_url` 内容传给模型 |
| `LLM_TIMEOUT_SECONDS` | `110` | 排队及模型调用共享的总时限 |
| `LLM_MAX_TOKENS` | `16384` | 思考及输出 token 总上限；生成被截断会明确报错 |
| `LOCAL_TOKEN` | 自动随机生成 | 本地搜题、日志和清缓存接口鉴权，与模型 Key 无关 |
| `PORT` | `8765` | 本地端口 |
| `CACHE_ENABLED` | `true` | 成功答案是否缓存 |
| `CACHE_TTL_SECONDS` | `604800` | 答案缓存有效期，默认 7 天，最多保留 5000 条 |
| `DB_PATH` | `data/quiz.sqlite3` | 数据库路径，相对路径以项目目录为基准 |

更改 `.env` 后重启生效。已有进程环境变量优先于 `.env`。代理若不接受 DeepSeek 思考参数，可用 `omit` 并将强度留空。服务不会在失败时自动删除思考参数或图片重试。

官方说明：[模型与视觉支持](https://api-docs.deepseek.com/)、[思考开关与强度](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat Completions 格式](https://api-docs.deepseek.com/api/create-chat-completion/)。默认使用启用思考及 `low` 强度。

## 图片和答案处理

- 从题目、选项中的 HTML `img` 地址、Markdown 图片地址和裸 HTTP(S) 地址提取图片；也接受 `images` 数组以及 base64 data URL，最多 8 张。无扩展名的图床地址也会被视为图片候选。
- 模型服务商直接读取图片链接。本地服务不下载图片，不转发浏览器 Cookie；登录才能访问的图片应由调用方提供 base64。`blob:` 地址、相对图片路径无法直接供模型读取。
- OCS 的题目提取逻辑必须把图片地址传到服务，才能识别图片。服务无法恢复 OCS 未提交的图片或截图。
- 图片关闭或模型接口拒绝图片时返回失败，不降级为文字猜测。无有效 JSON、答案不完整、选项无法匹配时也返回失败。
- 选择题字母转换为选项原文；选项按行排列。填空保留原始数组顺序及重复答案，返回 OCS 时使用 `#` 连接，这是 OCS 题库协议的分隔方式。
- 缓存键包含题目、选项、题型、图片、模型地址、模型名、思考配置和提示词。修改配置不会误用旧模型结果。图片链接内容变化但 URL 不变时，需手动清空缓存。

## 接口与验证

- `GET /api/health`：本地服务状态、Key 是否已填写；不会调用模型验证 Key。
- `GET /ocs-config.json`：供本机复制的 OCS 配置，含本地访问 Token，不含模型 Key。
- `POST /api/search`：Bearer 本地 Token；JSON `{ "title": "题目", "options": "选项1\n选项2", "type": "single" }`，可额外传 `images`。禁止请求覆盖服务端模型配置。
- `GET /api/logs`：Bearer 本地 Token，最近 100 条记录。
- `DELETE /api/cache`：Bearer 本地 Token，清空答案缓存。

成功返回 `code: 0` 和 `data.question / answers / reason / usage / latency_ms / cached`。业务失败返回 HTTP 200 + `code: 1 / msg`，以便 OCS 显示失败原因；鉴权失败返回 HTTP 401。

```powershell
./.venv/Scripts/python.exe -m pytest -q
```

测试使用模拟模型接口，验证 OCS 协议、服务端配置、图片内容、重复填空、鉴权、超时、失败不缓存和缓存过期，不消耗 API 额度。真实模型验证需要填写 Key 后在本地页面试搜。

`requirements-lock.txt` 记录已验证的依赖版本；启动脚本首次安装时使用该文件。22 项测试通过，依赖完整性检查通过；当前 Starlette 对测试客户端使用 httpx 有一条弃用提示，不影响测试结果。本地页面已通过实际浏览器检查，尚未验证真实 DeepSeek 请求和 OCS 端到端搜题。

`.env`、`.venv` 和 `data/` 已加入忽略规则。日志保存题目、选项、答案、简短依据和用量，不保存模型 Key、上游原始响应或模型思考过程。日志最多保留最近 500 条。仅搜题接口允许跨域；配置与日志页面供本机使用。题目和图片会发送到配置的模型服务商。

## 参考项目

题库协议参考 [ocs-quiz](https://github.com/swim233/ocs-quiz) 的接口结构，并以 Python 独立实现本地服务；不复制其 Cloudflare 部署实现。OCS 主程序：[ocs-desktop](https://github.com/ocsjs/ocs-desktop)。

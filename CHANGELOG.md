# 变更记录

## 0.1.0-rc.1（2026-10-30）

首个提交。内容为脱敏后的预发布候选源码加下列整理。

### 变更（影响现有部署）

- 统一遗留命名 `cindy`：systemd 服务名 `wechat-bot.service`；compose 镜像名 `wechat-bot-desktop:local`、容器名 `wechat-bot-desktop`；`agy_work_root` 默认值 `~/.local/share/wechat-bot/runtime/agy-work`。已有部署须同步改名，或在 `config.json` 中显式设置 `agy_work_root`。
- `agy_fallback` 的代码默认值由 `True` 改为 `False`。agy 失败时不再自动切换到实验后端（直连非公开接口）；需要时在配置中显式设为 `true`。
- 删除旧版回复前缀过滤 `LEGACY_PREFIX`（`[Cindy] `）与 `guardrails.LOCAL_EXPLICIT` 中的 `cindy` 关键词。

### 移除

- `model_sandbox.invoke()`：仓库内无调用方。`sandbox_options()` 等辅助函数仍保留，其中 `sandbox_options()` 目前仅由 `tests/test_os_sandbox.py` 使用。

### 新增

- `requirements.txt`、`deploy/wechat-bot.service`、`docs/DEPLOYMENT.md`、`docs/RELEASE_CHECKLIST.md`、`docs/architecture/`（技术架构报告）。
- 测试 `test_fallback_is_off_by_default`；两个回退测试改为显式声明 `agy_fallback=True`。

### 文档修正

- README 的 `net-guard` 构建命令加 `-static`；补充文档索引、服务名与回退默认值说明。

### 测试

- Python 3.12.3：326 项运行，无失败（跳过 2）；`RUN_OS_SANDBOX_TESTS=1` 且 `net-guard` 静态构建时同样无失败（跳过 1）。

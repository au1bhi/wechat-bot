# 变更记录

## 0.1.0-rc.2（2026-10-30）

### 安全

- agy 沙箱不再绑定真实的 D-Bus 会话总线。`agy_model.BusProxy` 用 `xdg-dbus-proxy --filter --talk=org.freedesktop.secrets` 提供过滤后的套接字，沙箱内只能访问密钥服务；缺少 `xdg-dbus-proxy` 时失败关闭。部署需安装 `xdg-dbus-proxy`。

### 修复

- 技术话题误拒答：`docker`、`容器`、`systemd`、`沙箱`、`subprocess`、`读取文件` 等词不再无条件命中 `local_information`。仅当句子指向机器人或其宿主（如“你运行在 docker 里吗”）或明确要求读取/执行本机内容时才由规则拒答。
- 健康检查：容器健康现在要求 noVNC 可达，且桥接 `/status` 报告微信已登录且未锁定（`healthcheck.py`）；微信掉线或桥接异常时容器显示 unhealthy。compose 需挂载 `healthcheck.py`。

### 测试

- 新增 `test_bus_filter.py`（总线过滤、缺代理失败关闭、误拦与探测拒答回归）与 `test_healthcheck.py`。Python 3.12：332 项运行，无失败（跳过 2）。

## 0.1.0-rc.1（2026-10-30）

首个提交。内容为脱敏后的源码加下列整理。

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

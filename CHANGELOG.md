# 变更记录

## 0.1.0-rc.2（2026-10-30）

### 安全

- agy 沙箱不再绑定真实的 D-Bus 会话总线。`agy_model.BusProxy` 用 `xdg-dbus-proxy --filter --talk=org.freedesktop.secrets` 提供过滤后的套接字，沙箱内只能访问密钥服务；缺少 `xdg-dbus-proxy` 时失败关闭。部署需安装 `xdg-dbus-proxy`。

### 修复

- 技术话题误拒答：`docker`、`容器`、`systemd`、`沙箱`、`subprocess`、`读取文件` 等词不再无条件命中 `local_information`。仅当句子指向机器人或其宿主（如“你运行在 docker 里吗”）或明确要求读取/执行本机内容时才由规则拒答。
- 健康检查：容器健康现在要求 noVNC 可达，且桥接 `/status` 报告微信已登录且未锁定（`healthcheck.py`）；微信掉线或桥接异常时容器显示 unhealthy。compose 需挂载 `healthcheck.py`。

- 桥接 `open_chat()` 不再回退到微信搜索框：群不在聊天列表里时直接报 `CHAT_NOT_FOUND`。搜索结果里的“网络搜索”条目会在微信上方弹出内置浏览器窗口，挡住主界面并导致其他群读取失败。

- 发图确认：看到“我发的图片”气泡后再等约 3 秒，若聊天里新增“Unable to send / Failed to send / 发送失败 / 无法发送”一行，则自动再发一次；仍失败才按 `uncertain` 处理。此前气泡一出现就记为已发送，导致失败的图片被当成成功。

- 读取前自动回到最新消息：聊天被滚到历史位置（例如人工翻看或扫描后没有复位）时，微信会在右下角显示“Go to the latest message”绿色按钮，此时只能读到旧消息、读不到新消息（实际出现过漏回 @ 的情况）。桥接 `snapshot` 现在会向下滚动直到该按钮连续三次消失；聊天本来在底部时不做任何操作。`/snapshot?keep=1` 可跳过此步（扫描历史用）。

### 新增

- 难题走高强度模型：数学、证明、算法与调试类问题（`worker.is_hard()` 由代码判断，不额外调用模型）改用 `agy_hard_model`（示例 `gemini-3.8-flash-high`），超时 `agy_hard_timeout`（默认 150 s）。该型号不预热（`agy_pool_floors` 设为 0），首次使用时才启动进程；分类器和审查仍用快速型号。
- 慢答案的进度说明：难题派发后先发一句“在算了”，30 s 和 60 s 仍未出结果再按已用时间补发，模型开始写答案后若又拖了 8 s 以上再发一句。内容只依据真实可知的信息（已用时间、模型是否已开始输出）；agy 不提供思考过程文本，因此不会编造“推到第几步”。说明消息不进入对话上下文。

- 公式图排版：模型一行一条写的步骤或编号列表此前被 LaTeX 当成空格并成一整段（“1. … 2. … 3. …”挤在一起）。`latex_render.preserve_breaks()` 现在在正文、环境和独立公式之外给这类行补 `\\`；空行（分段）、已有的 `\\`、`align`/`enumerate` 等环境内部和 `\[ \]`、`$$ $$` 内部保持原样。

- 漏读新消息：机器人刚发完公式图（最后一行是 Image）后，聊天窗口顶部被图片挤出，旧的“前缀对齐”和“唯一锚点”都对不上，新问题被当成“窗口重置”而静默吞掉。`new_rows()` 现在会在新窗口任意位置寻找最近见过的连续行块（块必须唯一，单行必须有信息量），再取其后的行；含糊的窗口仍不会凭空产生或隐藏消息。

- 漏答审计：新增 `audit.py`。机器人记住“正常流程已经判断过的行”，之后每次读群都核对窗口：被 @ 或引用机器人、从未进入过分类器、且后面 12 行内没有机器人回复的消息，等 20 秒宽限后自动排队回答并写一条 `Audit:` 警告。每个群每小时最多补 6 条；启动时屏幕上已有的行不审计；`audit: false` 可关闭；`status.json` 的 `audit_recovered` 记录补回次数。这是对“窗口对不上而静默吞消息”这一类问题的兜底。

### 测试

- 新增 `test_bus_filter.py`（总线过滤、缺代理失败关闭、误拦与探测拒答回归）、`test_healthcheck.py`、`test_send_failed.py`、`test_latex_breaks.py`、`test_new_rows_block.py`、`test_audit.py`。Python 3.12：332 项运行，无失败（跳过 2）。

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

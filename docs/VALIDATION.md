# 本轮验证

2026-10-29，在 `/home` 下的 ext4 临时工作区对脱敏后的源码执行：

- 从 net_guard.c 临时编译网络辅助程序；该二进制不进入仓库。
- RUN_OS_SANDBOX_TESTS=1、ResourceWarning 视为错误：325 项测试，0 失败、0 错误、1 跳过。
- 原目录已知真实密钥值匹配：0；已知私人标识匹配（含 Python 解码字符串）：0。
- 10 类敏感路径通过 Git 忽略规则验证，worker.py 未被误忽略。
- 不包含原始 benchmark、聊天、截图、state、runtime、secrets、config.json、二进制或原 Git 历史。

这不是完整 DLP 认证；不证明所有材料的版权归属。未在新机器扫码登录、调用真实模型或向群发消息，未完整构建/审计 Docker 镜像。现有线上部署未迁移或改写。

## 2026-10-30 复核（整理为发布版本时）

在 `/tmp` 临时副本中，Python 3.12.3、内核 7.0.0-38、`bwrap` 与 `gcc` 可用：

- 清理前（325 项）：默认运行无失败（跳过 2）。
- 清理后（326 项，新增 `test_fallback_is_off_by_default`）：默认运行无失败（跳过 2）；`RUN_OS_SANDBOX_TESTS=1` 且 `net-guard` 以 `-static` 构建时无失败（跳过 1）。
- `net-guard` 按 `cc -O2` 动态构建时，OS 沙箱用例失败：`bwrap: execvp /bin/net-guard: No such file or directory`。`model_sandbox.sandbox_options()` 的最小文件系统不含 libc，动态链接程序无法执行。README 已改为 `-static`。
- conda Python 3.11.17 缺少 `os.memfd_create`，agy 进程池相关用例出现错误（24 项 `AttributeError`，另有 4 项同组用例失败）；换用 3.12 后通过。

未做：全新机器安装验证、扫码登录、真实模型调用、向群发送消息。

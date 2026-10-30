# Linux WeChat automation

隔离虚拟桌面中的 Linux 微信界面自动化，Python 调度，外部模型生成和内容校验。不是腾讯官方机器人接口。

本仓库为脱敏版本：群名、昵称、真人映射和具体地名已替换为演示值；真实密钥、配置、登录资料、聊天记录、截图、原始 benchmark 与预编译二进制未包含。人设仍保留原行为结构，属于可替换的实验示例，不是现实人物资料或通用推荐默认值。

本项目原创部分采用 **MIT License**，见 [LICENSE](LICENSE)，版权署名为 `wechat-bot contributors`。允许商用、修改和再分发，须保留版权及许可声明，并按许可证不提供担保。第三方材料仍按各自许可和通知处理；主许可证不补足未知来源的授权。发布前阅读 `docs/PREPUBLICATION.md`、`docs/LICENSE_REVIEW.md` 和 `THIRD_PARTY_NOTICES.md`。

## 组成

- `worker.py`：读取、队列、防抖、上下文、安全判断、发送确认。
- `transport.py`：隔离桌面的 AT-SPI/X11 桥接。
- `agy_model.py`：外部 `agy` CLI 的单次隔离会话及预热池；普通 2 个，忙时上限 4 个。
- `fast_model.py` / `model_sandbox.py`：实验性的 ChatGPT 登录后端；涉及非公开接口；agy 失败后的自动回退默认关闭（`agy_fallback`，须显式设为 `true` 才启用）。
- `guardrails.py`、`topic_policy.py` 和 persona 模块：输入输出规则和可替换口吻；提示词不等于强制安全隔离。
- `net_guard.c`：需要在本机编译的网络边界辅助程序。
- `tests/`：脱敏后的回归样例；不包含群聊数据库和原始重放记录。

## 环境与检查

Linux（Landlock ABI ≥ 6）、Python 3.12，主进程需要 Pillow（`pip install -r requirements.txt`）；桥接需要 PyGObject/AT-SPI2、python-xlib；部署还需要 Docker/Compose、Xvfb/Openbox、D-Bus、Bubblewrap。公式渲染需要 XeLaTeX、dvipng/Poppler 工具和字体，按 `latex_render.py` 的实际命令检查依赖。镜像所需系统包列在 Dockerfile。此候选未完成全新机器安装验证。

复制 `config.example.json` 为本地 `config.json`，填入自己的群名、路径与凭据文件位置；实际配置被 Git 忽略。不要上传 auth.json、密钥、二维码或容器 home。

编译辅助程序及运行测试应在 ext4 等本机文件系统中进行，勿在已知有构建风险的 NTFS 数据盘执行：

```sh
mkdir -p bin
cc -O2 -Wall -Wextra -static net_guard.c -o bin/net-guard   # -static：实验后端的最小沙箱不含 libc，动态链接程序无法在其中执行
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
# 在具备 Bubblewrap/Landlock 与编译器的 Linux 环境额外检查：
RUN_OS_SANDBOX_TESTS=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

不要仅凭示例配置启动实号机器人。先配置密钥与白名单，再完成私有测试；`botctl` 使用的用户态 systemd 服务名为 `wechat-bot.service`，单元模板见 `deploy/wechat-bot.service`；完整步骤见 `docs/DEPLOYMENT.md`。项目不含 agy、微信或用户登录凭据；外部程序须通过各自官方渠道安装。

## 文档

- `docs/DEPLOYMENT.md`：部署步骤与首次启动核对清单。
- `docs/architecture/ARCHITECTURE.md`（另有 PDF）：技术架构报告，含模块依赖、数据流、安全设计、问题清单。
- `docs/VALIDATION.md`：验证记录；`docs/PREPUBLICATION.md`、`docs/LICENSE_REVIEW.md`、`docs/LICENSE_DECISION.md`：发布前整理与许可证审查。
- `docs/RELEASE_CHECKLIST.md`：公开前须由所有者确认的事项。
- `CHANGELOG.md`：变更记录。

## 模型服务边界

官方 headless 功能可被程序调用，不代表任何用途均获个人订阅授权。Antigravity FAQ 同时支持直接脚本/CI、限制个人订阅被第三方代理或应用封装；本项目不保证微信常驻机器人用途获准。Google API Key 模式与消费者订阅是不同接入方式。本项目当前代码也没有实现通用 Gemini API Key 后端。源码许可与模型/微信服务条款须分开核对。

## 发布前

- 主许可证已选 MIT；仍须核对贡献归属与第三方材料权利。
- 完成人设、样例和语料的人工审核；不要把“化名”当作敏感人物画像的充分授权。
- 参照许可证报告处理来源与依赖；不把微信、模型 CLI、字体或完整 Docker 镜像随源码打包。
- 本仓库是脱敏后新建的，没有沿用旧目录的任何 Git 历史。

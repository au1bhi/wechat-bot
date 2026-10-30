# 部署步骤

本文依据源码与配置文件整理。**未在全新机器上端到端验证**（与 README、`docs/VALIDATION.md` 一致）。

## 1. 前置条件

| 项 | 要求 |
|---|---|
| 系统 | Linux；Landlock ABI ≥ 6（内核 6.12 及以上）。可用 `./bin/net-guard /bin/true` 检查：退出码 0 为可用，121 为内核不支持 |
| 宿主机软件 | Python 3.12、Docker 与 Compose、Bubblewrap、`xdg-dbus-proxy`（把 agy 沙箱可见的 D-Bus 限制为密钥服务；缺失时 agy 启动失败而不会放宽）、C 编译器；公式渲染另需 XeLaTeX、Poppler（`pdftoppm`）与字体 |
| 微信客户端 | Linux 版安装在宿主机 `/opt/wechat`（compose 以只读方式挂入容器；本仓库不提供） |
| agy CLI | 自行从官方渠道安装并登录，默认路径 `~/.local/bin/agy`（配置项 `agy_bin`） |

## 2. 获取与构建

```sh
git clone <本仓库地址> wechat-bot && cd wechat-bot
python3 -m pip install -r requirements.txt     # 受 PEP 668 限制的发行版：改用 venv（--system-site-packages）或 apt install python3-pil
mkdir -p bin
cc -O2 -Wall -Wextra -static net_guard.c -o bin/net-guard      # -static 为实验后端沙箱所必需
docker build -t wechat-bot-desktop:local .
```

测试（在 ext4 等本机文件系统上执行，勿在 NTFS 数据盘上执行）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
RUN_OS_SANDBOX_TESTS=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

## 3. 配置与密钥

```sh
cp config.example.json config.json         # 填写群名、别名、agy 型号等；config.json 已被 .gitignore 忽略
umask 077
mkdir -p secrets state/desktop-home/bot-state
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > secrets/bridge_token
python3 -c "import secrets; print(secrets.token_urlsafe(16))" > secrets/vnc_password
python3 -c "import uuid; print(uuid.uuid4().hex)" > state/machine-id
```

要点：

- `config.json` 中的相对路径（`secrets/bridge_token`、`bin/net-guard`、`runtime/…`）按**当前工作目录**解析，worker 须在仓库根目录下运行。
- `private_markers` 应填入宿主机名、用户名、家目录片段等不得出现在回复中的标识；为空则该输出检查不生效。
- `agy_fallback` 默认关闭。只有明确接受实验后端（非公开接口）的风险时才设为 `true`。
- compose 以 `user: 1000:1000` 运行容器：`state/desktop-home` 须对 uid 1000 可写，`secrets/` 下的文件须对 uid 1000 可读。宿主用户 uid 不是 1000 时，需用 `chown` 或 ACL 调整。
- 使用 venv 时，`deploy/wechat-bot.service` 的 `ExecStart` 须改为 venv 内的 python3。

## 4. 容器状态目录（须手工创建）

仓库内没有任何代码写入下列文件。

| 文件 | 位置（宿主机） | 内容 |
|---|---|---|
| `chats.json` | `state/desktop-home/bot-state/chats.json` | JSON 数组，元素为桥接允许操作的群名（非空、≤ 100 字符）。缺省只允许环境变量 `BOT_CHAT` 指定的群，其余群返回 `CHAT_NOT_ALLOWED` |
| `owner.json` | `state/desktop-home/bot-state/owner.json` | 可选。`{"weixin_id": "…"}`；仅用于“所有者核验”，不授予任何权限 |

## 5. 启动与登录

```sh
docker compose up -d
./botctl desktop            # 打印 noVNC 地址，并在终端回显 VNC 密码
```

用浏览器打开 noVNC 地址，在桌面里的微信上扫码登录。随后安装 worker 服务：

```sh
mkdir -p ~/.config/systemd/user && cp deploy/wechat-bot.service ~/.config/systemd/user/
# 按实际路径修改 WorkingDirectory 与 ExecStart
systemctl --user daemon-reload && systemctl --user enable --now wechat-bot.service
```

## 6. 自检与运维

```sh
python3 worker.py --check-model     # 以“2+2”做一次端到端模型调用
./botctl status                     # systemd 状态、桥接状态与 state/status.json
./botctl pause                      # 创建 state/PAUSED，停止自动回复
./botctl resume                     # 删除 PAUSED 并启动服务
./botctl logs
```

发送结果无法确认时，worker 会自行写入 `state/PAUSED`（内容 `auto`）并停止回复，需确认聊天界面状态后执行 `./botctl resume`。

## 7. 首次启动前的核对清单

- [ ] `./bin/net-guard /bin/true` 退出码为 0
- [ ] `secrets/`、`state/`、`config.json` 均未被 Git 跟踪（`git status` 不应出现它们）
- [ ] `chats.json` 已列出全部要轮询的群
- [ ] `private_markers` 已填写
- [ ] 先在私有测试群中验证：@ 回复、拒绝路径、暂停与恢复

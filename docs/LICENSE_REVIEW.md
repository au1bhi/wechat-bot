# 许可证与服务条款风险审查

检查日期：2026-10-29。主许可证已由项目所有者授权选定为 MIT，根目录已生成 LICENSE，版权署名为 wechat-bot contributors。该选择覆盖项目有权许可的原创部分；第三方代码、语料、素材、专有客户端与服务仍按其各自条款处理。此报告是发布准备审查，非法律意见。

| 对象 | 证据与判断 | 发布前动作 |
|---|---|---|
| 本项目原创代码 | 主许可证已选 MIT，LICENSE 已生成；原目录无 Git 历史，完整贡献归属仍需确认 | 保留版权及许可声明；确认有权许可的范围，不将他人未知授权代码冒称 MIT |
| Humanizer-zh / humanizer | 当前主分支均为 MIT；本项目 style 文档明示参考改编 | 已保留两份完整版权/许可；补原取材提交版本更稳妥 |
| baiyingawa/wechat-cli | 本地固定提交与当前 GitHub 元数据均未发现明确许可证 | 不复制其代码；如存在实质派生，需取得授权或独立重写。无许可证不等于公有领域 |
| wx-11/MimicWX-Linux | 本地 Cargo.toml 与 README 声称 MIT，但本地无 LICENSE 文件，GitHub 未识别许可证 | 仅架构参考，不将其 checkout 带入；若复制代码需进一步确认作者版权声明/完整许可。不能直接断言无任何许可 |
| thisnick/agent-wechat | 当前仓库 MIT；作为调研来源，并非直接运行依赖 | 若引入实质代码，连同版权许可一起引入 |
| Olcmyk/HuChenFeng 与网页语料 | 转写仓库标 MIT 不代表拥有视频/讲话/第三方内容全部著作权；新闻、Wikiquote、图片各有权利边界 | 当前只留少量短语与自行概括，未打包原始直播/梗图；仍须逐项审核，不可宣称整包任意商用 |
| Python、Pillow、python-xlib、PyGObject、Bubblewrap、X11/VNC/noVNC、TeX、字体 | 多个宽松、LGPL、GPL及字体许可，不是一张 MIT 覆盖所有组件 | 仅源码引用不自动使本项目变 GPL；若发布预构建二进制/镜像，必须做精确版本 SBOM、许可通知及适用源码/重链接等义务核查，本次未完成完整镜像清单 |
| WeChat、agy/Antigravity、Google/ChatGPT 账号服务 | 专有软件与服务条款，不由项目开源许可证授权 | 不分发客户端、登录资料或模型 CLI；只指引官方安装。消费者订阅封装限制/非公开 ChatGPT 接口属于独立服务接入风险，不能用项目 MIT 许可消除 |

没有发现本候选直接 vendoring 上述无许可证项目整库的证据；但本地短片段相似度检查只比较 Python 文本，不能证明所有代码均独立创作。`MimicWX` 原本为 Rust，未完整审计每个 Docker/脚本片段。当前应视为“来源待确认”，而非无风险认证。

## 一手证据

- 项目许可选择：https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository
- https://raw.githubusercontent.com/op7418/Humanizer-zh/main/LICENSE
- https://raw.githubusercontent.com/blader/humanizer/main/LICENSE
- https://github.com/baiyingawa/wechat-cli
- https://github.com/wx-11/MimicWX-Linux/blob/main/Cargo.toml
- https://github.com/thisnick/agent-wechat/blob/main/LICENSE
- https://github.com/Olcmyk/HuChenFeng
- https://antigravity.google/docs/faq/
- https://antigravity.google/terms

本地调研快照：wechat-cli `5b152c5547b333db8f73fdb9c4276984f27a97a0`；MimicWX `a42a3eec4e6efa2d023915e980e9af7d5fcf9439`。公共主分支可能变化。

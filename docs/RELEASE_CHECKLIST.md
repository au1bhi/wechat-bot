# 公开前须由所有者确认的事项

仓库先以私有状态创建。以下事项依赖仓库所有者的判断或外部事实，自动化检查无法替代。来源见 `docs/PREPUBLICATION.md` 与 `docs/LICENSE_REVIEW.md`。

- [ ] **代码来源**：确认原创部分的贡献归属，以及没有他人未知授权的代码被当作 MIT 发布。
- [ ] **人设、样例与语料**：人工复核 `style_guide.py`、`slang.py`、`persona_*.py`、`huchenfeng.py`、`social_language.py` 中的短语、释义与链接；不得把化名当作敏感人物画像的充分授权。
- [ ] **第三方权利与服务条款**：确认微信、agy/Antigravity 与模型账号服务的条款允许你的使用方式；MIT 许可不覆盖这些服务。
- [ ] **全新机器部署测试**：按 `docs/DEPLOYMENT.md` 在干净环境端到端验证一次。
- [ ] **提交历史**：`git log --format='%an <%ae>'` 只应出现 noreply 地址。

确认后改为公开：

```sh
gh repo edit <owner>/wechat-bot --visibility public --accept-visibility-change-consequences
```

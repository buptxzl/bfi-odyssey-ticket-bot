# BFI IMAX《The Odyssey》Telegram 刷票提醒：GitHub Actions 版

这个版本不需要 Railway，也不需要电脑持续开机。GitHub Actions 会定时加载 BFI 页面；检测到购票或选座入口后，向 Telegram 发送通知。它不登录、不绕验证码、不自动购买。

## 上传到你现有的仓库

1. 下载并解压此文件。
2. 打开 GitHub 上的 `bfi-odyssey-ticket-bot` 仓库。
3. 点击 **Add file → Upload files**。
4. 上传解压后文件夹中的全部内容，并覆盖同名文件。
5. 点击 **Commit changes**。

关键新增文件是：

```text
.github/workflows/check-tickets.yml
check_once.py
```

原来的 `Dockerfile` 和 `railway.json` 可删除，也可保留；GitHub Actions 不会使用它们。

## 设置 Telegram Secrets

进入仓库：**Settings → Secrets and variables → Actions → New repository secret**，创建两个 Secret：

- Name：`TELEGRAM_BOT_TOKEN`；Secret：BotFather 给你的新 Token。
- Name：`TELEGRAM_CHAT_ID`；Secret：你的 Chat ID（你的是 `8662318567`）。

名称必须完全一致。不要把 Token 写进代码，也不要再发到聊天里。

## 第一次测试

1. 点击仓库顶部 **Actions**。
2. 左侧选择 **Check BFI tickets**。
3. 点击 **Run workflow**。
4. 保持测试消息选项为勾选，再点击绿色 **Run workflow**。
5. 等待约 1–3 分钟。成功后 Telegram 会收到：

```text
✅ BFI 刷票机器人测试成功。GitHub Actions 已能向你发送 Telegram 通知。
```

## 自动检查频率

工作流设置为每 5 分钟尝试检查一次：

```yaml
- cron: "*/5 * * * *"
```

GitHub 的定时任务可能因平台繁忙而延迟，并不保证精确到秒。

## 买到票后停止

进入 **Actions → Check BFI tickets**，点击右上角菜单并选择 **Disable workflow**。否则页面持续显示购票入口时，机器人可能重复提醒。

## 安全

你之前展示过旧 Token。请先在 BotFather 使用 `/revoke` 生成新 Token，只把新 Token存入 GitHub Secret。

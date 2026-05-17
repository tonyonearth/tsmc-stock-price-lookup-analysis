# LINE 設定重點（給這個專案用）

## 1. 這個專案有兩種 LINE 用法

### 用法 A：daily_tsmc_report.py 直接 push 摘要
這條線只需要：
- LINE_CHANNEL_ACCESS_TOKEN
- LINE_TO_ID

不需要 webhook。

### 用法 B：OpenClaw 接 LINE 作為查詢入口
這條線需要：
- LINE_CHANNEL_ACCESS_TOKEN
- LINE_CHANNEL_SECRET
- 可被 LINE 呼叫到的 HTTPS webhook URL

## 2. 若你只想先做每日主動推播
你只需要先把：
- `LINE_PUSH_ENABLED=true`
- `LINE_CHANNEL_ACCESS_TOKEN=...`
- `LINE_TO_ID=...`
填進本專案 `.env`

## 3. `LINE_TO_ID` 怎麼來？
最實用做法有兩種：
1. 之後若你也把 OpenClaw 接上 LINE，就直接用同一個 LINE user ID
2. 自己做一個最小 webhook 觀察 incoming event，把 `source.userId` 抄下來

## 4. OpenClaw 接 LINE 時的角色
建議讓 OpenClaw 只做：
- status
- summary
- latest
- push

不要讓它負責重跑 Gemini，這樣最省額度，也最穩。

## 5. OpenClaw 的 webhook URL
若你的 gateway 對外網址是：
https://your-domain.example

則 LINE Developers Console 裡的 webhook URL 一般就是：
https://your-domain.example/line/webhook

若你在 openclaw.json 有改 `channels.line.webhookPath`，則需跟著調整。

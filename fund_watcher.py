import json
import logging
import os
import re
from datetime import datetime

import requests
from lxml import etree
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.ERROR)

# ======================
# 配置
# ======================
BOT_TOKEN = os.environ["BOT_TOKEN"]
STATE_FILE = "fund_state.json"

# {"users": {"<chat_id>": {"funds": {code: {name, limit, updated}}}}}
state = {"users": {}}


# ======================
# 状态
# ======================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"users": {}}
    with open(STATE_FILE, "r") as f:
        data = json.load(f)
    # migrate old single-user format
    if "funds" in data and "users" not in data:
        return {"users": {"legacy": {"funds": data["funds"]}}}
    return data


def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False)


def get_user_funds(chat_id: str) -> dict:
    user = state["users"].setdefault(chat_id, {"funds": {}})
    return user.setdefault("funds", {})


# ======================
# HTTP
# ======================
def fetch_html(url):
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.encoding = "utf-8"
    return resp.text


# ======================
# 限购解析
# ======================
def parse_amount(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*元", text)
    if m:
        return float(m.group(1)) * 10000

    m = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    if m:
        return float(m.group(1))

    return None


def fetch_fund_info(code) -> tuple:
    """Fetch name and purchase limit in a single HTTP request."""
    html_text = fetch_html(f"https://fund.eastmoney.com/{code}.html")
    html = etree.HTML(html_text)

    name_nodes = html.xpath("//div[contains(@class,'fundDetail')]//h1/text()")
    if name_nodes:
        name = name_nodes[0].strip()
    else:
        m = re.search(r"<title>(.*?)基金净值", html_text)
        name = m.group(1).strip() if m else None

    nodes = html.xpath("//div[@class='buyWayWrap']//span")
    texts = [
        n.xpath("string(.)").strip()
        for n in nodes
        if n.xpath("string(.)").strip()
    ]

    limit = None
    for i, t in enumerate(texts):
        if "交易状态" in t and i + 1 < len(texts):
            status = texts[i + 1]
            if "暂停" in status:
                limit = 0
            elif "开放申购" in status:
                limit = float("inf")
            else:
                limit = parse_amount(status)
            break

    return name, limit


# ======================
# 事件判断
# ======================
def check_event(name, old, new):
    if old == 0 and new > 0:
        return f"🟢恢复申购 {name}\n{fmt_limit(new)}"

    if new == float("inf") and old != float("inf"):
        return f"🚀完全放开 {name}"

    if old is not None and new is not None:
        if new > old:
            return f"📈额度提升 {name}\n{fmt_limit(old)} → {fmt_limit(new)}"
        if new < old:
            return f"⚠️额度收紧 {name}\n{fmt_limit(old)} → {fmt_limit(new)}"

    return None


def fmt_limit(v):
    if v == 0:
        return "⛔ 暂停"
    if v == float("inf"):
        return "🚀 无限"
    if v is None:
        return "❓ 未知"
    if v >= 10000:
        return f"{v / 10000:.2f} 万元"
    return f"{v:.2f} 元"


# ======================
# 命令：add
# ======================
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法：/add 018147")
        return

    code = context.args[0]
    chat_id = str(update.effective_chat.id)

    name, limit = fetch_fund_info(code)

    funds = get_user_funds(chat_id)
    funds[code] = {
        "name": name,
        "limit": limit,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state()

    icon = "🟢" if limit == float("inf") else "🔴" if not limit else "🟡"

    await update.message.reply_text(
        f"""✅ 已加入监控

📌 名称：{name}
🆔 代码：{code}
{icon} 当前额度：{fmt_limit(limit)}"""
    )


# ======================
# 命令：addall
# ======================
async def addall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args)
    codes = list(set(re.findall(r"\d{6}", raw)))

    if not codes:
        await update.message.reply_text("未识别到基金代码")
        return

    chat_id = str(update.effective_chat.id)
    funds = get_user_funds(chat_id)
    added = []

    for code in codes:
        name, limit = fetch_fund_info(code)

        funds[code] = {
            "name": name,
            "limit": limit,
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        added.append(f"✔ {name} 🆔: {code}")

    save_state()

    await update.message.reply_text("📦 批量添加完成\n\n" + "\n".join(added))


# ======================
# 命令：remove
# ======================
async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("用法：/remove 018147")
        return

    code = context.args[0]
    chat_id = str(update.effective_chat.id)
    funds = get_user_funds(chat_id)

    if code in funds:
        name = funds[code]["name"]
        funds.pop(code)
        save_state()

        await update.message.reply_text(
            f"""🗑 已移除监控

📌 {name}
🆔 {code}"""
        )
    else:
        await update.message.reply_text("⚠️ 未找到该基金")


# ======================
# 命令：list
# ======================
async def list_funds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    funds = get_user_funds(chat_id)

    if not funds:
        await update.message.reply_text("📭 监控列表为空")
        return

    lines = ["📊 基金监控（含更新时间）"]

    for code, v in funds.items():
        icon = (
            "🟢"
            if v["limit"] == float("inf")
            else "🔴"
            if v["limit"] == 0
            else "🟡"
        )

        updated = v.get("updated", "未知时间")

        lines.append("")
        lines.append(f"{icon} {v['name']}")
        lines.append(f"   🆔 {code}")
        lines.append(f"   💰 {fmt_limit(v['limit'])}")
        lines.append(f"   ⏱ {updated}")

    await update.message.reply_text("\n".join(lines))


HELP_TEXT = """
📊 基金申购额度监控 Bot

可用命令：

/add 代码
  添加单只基金监控
  例：/add 018147

/addall 代码列表
  批量添加基金
  例：/addall 018147, 019455

/remove 代码
  移除基金监控
  例：/remove 018147

/list
  查看当前监控列表

/help
  显示帮助信息
"""


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


# ======================
# 监控任务（JobQueue）
# ======================
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    for chat_id, user_data in list(state.get("users", {}).items()):
        funds = user_data.get("funds", {})
        for code, info in funds.items():
            try:
                _, new_limit = fetch_fund_info(code)
                old_limit = info["limit"]

                if new_limit is None:
                    continue

                if new_limit != old_limit:
                    msg = check_event(info["name"], old_limit, new_limit)
                    if msg:
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                    info["limit"] = new_limit

                info["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            except Exception as e:
                logging.error(f"monitor error {chat_id}/{code}: {e}")

        save_state()


# ======================
# main
# ======================
def main():
    global state
    state = load_state()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("addall", addall))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_funds))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    app.job_queue.run_repeating(monitor_job, interval=25000, first=5)

    app.run_polling()


if __name__ == "__main__":
    main()

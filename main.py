from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import aiohttp
import json
import os
from datetime import datetime
from zhdate import ZhDate
import asyncio

def count_rune(s: str) -> int:
    """等价Go utf8.RuneCountInString，统计Unicode字符数"""
    return len(list(s))

@register("bilibili_danmaku", "limou3434", "梦寝兔兔专用群聊插件：QQ留言转B站弹幕 + 生日定时私聊提醒", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.api_endpoint = "http://172.18.167.28:8023/send_danmaku"
        self.max_danmaku_len = 35
        self.data_dir = os.path.join("data", "bilibili_danmaku")
        self.data_path = os.path.join(self.data_dir, "birthday_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.birth_data = self.load_birth_data()
        self.birth_task = None

    def load_birth_data(self):
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"生日数据读取失败: {e}")
        return {
            "notify_enable": True,
            "anchor_qq": "",
            "manager_qq": "",
            "anchor_umo": "",
            "manager_umo": "",
            "birthday_list": []
        }
    
    def save_birth_data(self):
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(self.birth_data, f, ensure_ascii=False, indent=2)
    
    async def initialize(self):
        self.birth_task = asyncio.create_task(self.birth_loop())
    
    async def birth_loop(self):
        # 每日早上8点执行生日检查
        while True:
            now = datetime.now()
            next_run = datetime(now.year, now.month, now.day, 8, 0, 0)
            if now >= next_run:
                next_run = next_run.replace(day=now.day + 1)
            sleep_sec = (next_run - now).total_seconds()
            await asyncio.sleep(sleep_sec)
            await self.daily_birthday_check()
    
    @filter.command("你好")
    async def helloworld(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        message_chain = event.get_messages()
        logger.info(message_chain)
        yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!")
    
    @filter.command("留言")
    async def send(self, event: AstrMessageEvent, msg: str = ""):
        """指令：/留言 内容"""
        user_name = event.get_sender_name()
        if not msg.strip():
            yield event.plain_result("❌ 啊啊啊留言内容不能为空哇！用法：/留言 你想说的话的说（认真）")
            return
        short_name = user_name[:5]
        full_danmaku = f"【{short_name}】留言：{msg.strip()}"
        rune_cnt = count_rune(full_danmaku)
        if rune_cnt > self.max_danmaku_len:
            yield event.plain_result(
                f"❌ 留言过长！\n完整弹幕预览：{full_danmaku}\n最大允许{self.max_danmaku_len}字符，当前{rune_cnt}字符"
            )
            return
        try:
            params = {
                "msg": full_danmaku
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_endpoint,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp_text = await resp.text()
                    logger.info(f"Go返回：{resp_text}")
                    yield event.plain_result(f"✅ 留言弹幕已提交到直播间")
        except aiohttp.ClientConnectionError:
            yield event.plain_result("❌ 无法连接弹幕后端，请检查 Go 服务是否启动，确认 172.18.167.28:8023 网络连通")
        except aiohttp.ClientError:
            yield event.plain_result("❌ 网络请求异常，调用弹幕接口失败")
        except TimeoutError:
            yield event.plain_result("❌ 请求超时，Go 服务响应超时")
        except Exception as e:
            yield event.plain_result(f"❌ 未知错误：{str(e)}")
    
    @filter.command("生日记录")
    async def record_birthday(self, event: AstrMessageEvent):
        """/生日记录 昵称:农历/日历:月份:日期"""
        raw_text = event.message_str.strip()
        parts = raw_text.split(":")
        if len(parts) != 4:
            yield event.plain_result("❌ 参数格式错误！\n用法：/生日记录 昵称:农历/日历:月份:日期\n例：/生日记录 阿白:农历:8:15")
            return
        name, date_type, month_str, day_str = parts
        if date_type not in ("农历", "日历"):
            yield event.plain_result("❌ 第二个参数只能填写：农历 或者 日历")
            return
        try:
            month = int(month_str)
            day = int(day_str)
        except ValueError:
            yield event.plain_result("❌ 月份、日期必须是纯数字！")
            return
        try:
            if date_type == "日历":
                datetime(2025, month, day)
            else:
                ZhDate(2025, month, day).to_datetime()
        except Exception:
            yield event.plain_result("❌ 生日日期不合法，请重新输入！")
            return
        exist = False
        for item in self.birth_data["birthday_list"]:
            if item["name"] == name:
                item["type"] = date_type
                item["month"] = month
                item["day"] = day
                exist = True
                break
        if not exist:
            self.birth_data["birthday_list"].append({
                "name": name,
                "type": date_type,
                "month": month,
                "day": day
            })
        self.save_birth_data()
        yield event.plain_result(f"✅ 生日记录成功！\n{name}｜{date_type} {month}月{day}日")

    @filter.command("生日通知")
    async def toggle_birth_notify(self, event: AstrMessageEvent, msg: str = ""):
        """/生日通知 开 / /生日通知 关"""
        arg = msg.strip()
        if arg == "开":
            self.birth_data["notify_enable"] = True
            self.save_birth_data()
            yield event.plain_result("✅ 生日提醒已开启，生日当天会私聊主播和管理")
        elif arg == "关":
            self.birth_data["notify_enable"] = False
            self.save_birth_data()
            yield event.plain_result("✅ 生日提醒已关闭")
        else:
            yield event.plain_result("❌ 参数只能是【开】或者【关】\n用法：/生日通知 开")

    @filter.command("生日列表")
    async def show_birth_list(self, event: AstrMessageEvent):
        """/生日列表 查看所有登记的生日"""
        lst = self.birth_data["birthday_list"]
        if not lst:
            yield event.plain_result("📭 暂无登记的生日记录")
            return
        msg = "📋 已登记生日列表：\n"
        for item in lst:
            msg += f"{item['name']} | {item['type']} {item['month']}月{item['day']}日\n"
        yield event.plain_result(msg)

    @filter.command("生日移除")
    async def remove_birthday(self, event: AstrMessageEvent, msg: str = ""):
        """/生日移除 昵称，删除对应人的生日记录"""
        target_name = msg.strip()
        if not target_name:
            yield event.plain_result("❌ 需要填写昵称，用法：/生日移除 阿白")
            return
        old_len = len(self.birth_data["birthday_list"])
        self.birth_data["birthday_list"] = [item for item in self.birth_data["birthday_list"] if item["name"] != target_name]
        if len(self.birth_data["birthday_list"]) < old_len:
            self.save_birth_data()
            yield event.plain_result(f"✅ 已移除【{target_name}】的生日记录")
        else:
            yield event.plain_result(f"❌ 找不到【{target_name}】的生日记录")

    @filter.command("设置主播")
    async def set_anchor_qq(self, event: AstrMessageEvent, msg: str = ""):
        """/设置主播 12345678"""
        qq = msg.strip()
        self.birth_data["anchor_qq"] = qq
        self.save_birth_data()
        yield event.plain_result(f"✅ 主播提醒 QQ 已设置为：{qq}")

    @filter.command("设置管理")
    async def set_manager_qq(self, event: AstrMessageEvent, msg: str = ""):
        """/设置管理 12345678"""
        qq = msg.strip()
        self.birth_data["manager_qq"] = qq
        self.save_birth_data()
        yield event.plain_result(f"✅ 管理提醒 QQ 已设置为：{qq}")

    @filter.command("绑定主播")
    async def bind_anchor(self, event: AstrMessageEvent):
        """/绑定主播，主播私聊机器人执行，保存私聊会话标识"""
        self.birth_data["anchor_umo"] = event.unified_msg_origin
        self.save_birth_data()
        yield event.plain_result("✅ 主播会话绑定成功！后续生日提醒将发送到当前私聊会话")

    @filter.command("绑定管理")
    async def bind_manager(self, event: AstrMessageEvent):
        """/绑定管理，管理私聊机器人执行，保存私聊会话标识"""
        self.birth_data["manager_umo"] = event.unified_msg_origin
        self.save_birth_data()
        yield event.plain_result("✅ 管理会话绑定成功！后续生日提醒将发送到当前私聊会话")

    @filter.command("查看接收")
    async def show_notify_target(self, event: AstrMessageEvent):
        """/查看接收，查看当前配置的主播、管理QQ与绑定状态"""
        anchor_qq = self.birth_data.get("anchor_qq", "未设置")
        manager_qq = self.birth_data.get("manager_qq", "未设置")
        anchor_bind = "已绑定" if self.birth_data.get("anchor_umo") else "未绑定"
        manager_bind = "已绑定" if self.birth_data.get("manager_umo") else "未绑定"
        status = "开启" if self.birth_data.get("notify_enable") else "关闭"
        msg = (
            f"📩生日通知配置\n"
            f"通知状态：{status}\n"
            f"主播 QQ：{anchor_qq} | {anchor_bind}\n"
            f"管理 QQ：{manager_qq} | {manager_bind}"
        )
        yield event.plain_result(msg)

    @filter.command("立刻通知")
    async def test_notify(self, event: AstrMessageEvent):
        """/立刻通知，立刻发送一次生日提醒给主播和管理，用来测试私聊通知功能"""
        anchor_umo = self.birth_data.get("anchor_umo", "")
        manager_umo = self.birth_data.get("manager_umo", "")
        notify_enable = self.birth_data.get("notify_enable", False)

        if not notify_enable:
            yield event.plain_result("❌ 当前生日通知总开关是关闭状态，无法发送测试消息，请先 /生日通知 开")
            return
        if not anchor_umo and not manager_umo:
            yield event.plain_result("❌ 主播、管理会话都未绑定，请主播/管理私聊机器人执行 /绑定主播 /绑定管理")
            return
        
        test_msg = "🧪【测试提醒】生日通知功能测试，这条是手动触发的消息，不是定时任务！"
        send_list = []
        try:
            if anchor_umo:
                await self.context.send_message(anchor_umo, test_msg)
                send_list.append("主播")
            if manager_umo:
                await self.context.send_message(manager_umo, test_msg)
                send_list.append("管理")
        except Exception as e:
            logger.error(f"发送测试通知异常: {e}")
            yield event.plain_result(f"⚠️ 消息发送出错：{str(e)}")
            return
        
        yield event.plain_result(f"✅ 测试消息已发送给：{','.join(send_list)}")

    async def daily_birthday_check(self):
        if not self.birth_data["notify_enable"]:
            return
        anchor_umo = self.birth_data.get("anchor_umo", "")
        manager_umo = self.birth_data.get("manager_umo", "")
        if not anchor_umo and not manager_umo:
            logger.warning("主播和管理会话都未绑定，无法发送生日提醒，请使用 /绑定主播 /绑定管理")
            return
        today = datetime.now()
        birthday_names = []
        for item in self.birth_data["birthday_list"]:
            try:
                if item["type"] == "日历":
                    if today.month == item["month"] and today.day == item["day"]:
                        birthday_names.append(item["name"])
                else:
                    lunar_birth = ZhDate(today.year, item["month"], item["day"])
                    solar_birth = lunar_birth.to_datetime()
                    if solar_birth.month == today.month and solar_birth.day == today.day:
                        birthday_names.append(item["name"])
            except Exception as e:
                logger.warning(f"生日解析异常 {item}：{e}")
        if birthday_names:
            msg_text = f"🎂 今日生日提醒！\n{','.join(birthday_names)} 今天过生日！"
            try:
                if anchor_umo:
                    await self.context.send_message(anchor_umo, msg_text)
                    logger.info(f"生日提醒发送给主播会话: {msg_text}")
                if manager_umo:
                    await self.context.send_message(manager_umo, msg_text)
                    logger.info(f"生日提醒发送给管理会话: {msg_text}")
            except Exception as e:
                logger.error(f"定时生日通知发送失败: {e}")

    async def terminate(self):
        if self.birth_task:
            self.birth_task.cancel()
            try:
                await self.birth_task
            except asyncio.CancelledError:
                logger.info("生日定时任务已取消")

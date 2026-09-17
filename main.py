from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import aiohttp
import json
import os
from datetime import datetime
from zhdate import ZhDate

def count_rune(s: str) -> int:
    """等价Go utf8.RuneCountInString，统计Unicode字符数"""
    return len(list(s))

@register("bilibili_danmaku", "limou3434", "将QQ留言转为B站直播间弹幕，调用Go后端接口", "1.0.0")
class MyPlugin(Star): # 插件需要继承 Star 类，具体的处理函数 Handler 在插件类中定义，如这里的 helloworld 函数
    def __init__(self, context: Context): # Context 类用于插件与 AstrBot Core 交互，可以由此调用 AstrBot Core 提供的各种 API
        super().__init__(context)

        self.api_endpoint = "http://172.18.167.28:8023/send_danmaku" # Go 弹幕接口内网地址
        self.max_danmaku_len = 35 # 和 Go 服务保持一致：【sender】msg 拼接，总上限 30 字符

        self.data_dir = os.path.join("data", "bilibili_danmaku")
        self.data_path = os.path.join(self.data_dir, "birthday_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.birth_data = self.load_birth_data()
    
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
            "birthday_list": []
        }

    def save_birth_data(self):
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(self.birth_data, f, ensure_ascii=False, indent=2)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
    
    @filter.command("helloworld")
    async def helloworld(self, event: AstrMessageEvent):
        """这是一个 hello world 指令，AstrMessageEvent 是 AstrBot 的消息事件对象，存储了消息发送者、消息内容等信息，而 AstrBotMessage 是 AstrBot 的消息对象，存储了消息平台下发的消息的具体内容，可以通过 event.message_obj 获取""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
        user_name = event.get_sender_name() # 获取发送者 QQ 昵称
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链 from astrbot.api.message_components import *
        logger.info(message_chain)
        yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!") # 发送一条纯文本消息
    
    @filter.command("留言")
    async def send(self, event: AstrMessageEvent, msg: str = ""):
        """指令：/留言 内容"""
        user_name = event.get_sender_name()
        if not msg.strip():
            yield event.plain_result("❌ 啊啊啊留言内容不能为空哇！用法：/留言 你想说的话的说（认真）")
            return

        # 昵称裁剪最多5字符
        short_name = user_name[:5]
        # 插件在这里组装完整弹幕
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
    async def toggle_birth_notify(self, event: AstrMessageEvent):
        """/生日通知 开 / /生日通知 关"""
        arg = event.message_str.strip()
        if arg == "开":
            self.birth_data["notify_enable"] = True
            self.save_birth_data()
            yield event.plain_result("✅ 生日提醒已开启，生日当天会私聊主播")
        elif arg == "关":
            self.birth_data["notify_enable"] = False
            self.save_birth_data()
            yield event.plain_result("✅ 生日提醒已关闭")
        else:
            yield event.plain_result("❌ 参数只能是【开】或者【关】\n用法：/生日通知 开")

    @filter.command("设置主播")
    async def set_anchor_qq(self, event: AstrMessageEvent):
        """/设置主播 12345678"""
        qq = event.message_str.strip()
        self.birth_data["anchor_qq"] = qq
        self.save_birth_data()
        yield event.plain_result(f"✅ 主播提醒 QQ 已设置为：{qq}")

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

    @filter.scheduled_rule("0 0 8 * * *")
    async def daily_birthday_check(self):
        if not self.birth_data["notify_enable"]:
            return
        anchor_qq = self.birth_data.get("anchor_qq", "")
        if not anchor_qq:
            logger.warning("未设置主播 QQ，无法发送生日提醒")
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
            msg = f"🎂 今日生日提醒！\n{','.join(birthday_names)} 今天过生日！"
            await self.context.send_private_message(anchor_qq, msg)
            logger.info(f"生日提醒已发送给主播 {anchor_qq}: {msg}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

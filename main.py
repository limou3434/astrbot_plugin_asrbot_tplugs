from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.event import MessageChain
import aiohttp
import json
import os
from datetime import datetime
from zhdate import ZhDate
import asyncio

@register("bilibili_danmaku", "limou3434", "梦寝兔兔专用群聊插件", "1.1.1")
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

    def count_rune(self, s: str) -> int:
        """等价Go utf8.RuneCountInString，统计Unicode字符数"""
        return len(list(s))

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
            "notify_time": "8:0:0",
            "birthday_list": []
        }

    def save_birth_data(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.birth_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"生日数据保存失败: {e}")

    async def initialize(self):
        self.birth_task = asyncio.create_task(self.birth_loop())

    async def daily_birthday_check(self):
        # 总开关判断
        if not self.birth_data.get("notify_enable", False):
            logger.info("生日通知总开关关闭，跳过本次定时提醒")
            return

        today = datetime.now()
        birthday_names = []
        lunar_today = ZhDate.from_datetime(today)
        for item in self.birth_data["birthday_list"]:
            try:
                if item["type"] == "国历":
                    if today.month == item["month"] and today.day == item["day"]:
                        birthday_names.append(item["name"])
                else:
                    # 农历生日：对比今日农历月日
                    if lunar_today.month == item["month"] and lunar_today.day == item["day"]:
                        birthday_names.append(item["name"])
            except Exception as e:
                logger.warning(f"生日解析异常 {item}：{e}")

        logger.info(f"生日定时检查完成，匹配到今日生日名单：{birthday_names}")
        if not birthday_names:
            logger.info("今日无生日，不发送通知")
            return

        msg_text = f"🎂 今日生日提醒！\n{','.join(birthday_names)} 今天过生日！"
        try:
            anchor_umo = self.birth_data.get("anchor_umo", "")
            manager_umo = self.birth_data.get("manager_umo", "")
            msg_chain = MessageChain([Plain(msg_text)])
            # 主播、管理 两个都发
            if anchor_umo != "":
                await self.context.send_message(anchor_umo, msg_chain)
                logger.info(f"生日提醒发送给主播会话: {msg_text}")
            if manager_umo != "":
                await self.context.send_message(manager_umo, msg_chain)
                logger.info(f"生日提醒发送给管理会话: {msg_text}")
        except Exception as e:
            logger.error(f"定时生日通知发送失败: {e}")

    async def birth_loop(self):
        while True:
            try:
                now = datetime.now()
                time_str = self.birth_data.get("notify_time", "8:0:0")
                h_str, m_str, s_str = time_str.split(":")
                h = int(h_str)
                mi = int(m_str)
                sec = int(s_str)
                target = datetime(now.year, now.month, now.day, h, mi, sec)
                # 如果当前时间已经超过目标时间，则目标改为明天同一时刻
                if now > target:
                    target = target.replace(day=now.day + 1)
                sleep_sec = (target - now).total_seconds()
                logger.info(f"生日定时任务等待 {sleep_sec:.1f}s 后执行，目标时间：{target.strftime('%Y-%m-%d %H:%M:%S')}")
                await asyncio.sleep(sleep_sec)
                # 到点执行生日检查
                await self.daily_birthday_check()
            except Exception as e:
                logger.error(f"生日定时循环异常，10秒后重试: {e}")
                await asyncio.sleep(10)

    @filter.command("你好")
    async def helloworld(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(message_str)
        yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!")

    @filter.command("留言")
    async def send(self, event: AstrMessageEvent):
        """指令：留言 内容"""
        raw_msg = event.message_str.strip()
        msg = raw_msg.replace("留言","").strip()
        user_name = event.get_sender_name()
        if not msg.strip():
            yield event.plain_result("❌ 啊啊啊留言内容不能为空哇！用法：留言 你想说的话的说（认真）")
            return
        short_name = user_name[:5]
        full_danmaku = f"【{short_name}】留言：{msg.strip()}"
        rune_cnt = self.count_rune(full_danmaku)
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

    @filter.command("是否通知")
    async def toggle_birth_notify(self, event: AstrMessageEvent):
        raw_text = event.message_str.strip()
        arg = raw_text.replace("是否通知","").strip()
        if arg == "开":
            self.birth_data["notify_enable"] = True
            self.save_birth_data()
            yield event.plain_result("✅ 生日提醒已开启，生日当天会私聊主播和管理")
        elif arg == "关":
            self.birth_data["notify_enable"] = False
            self.save_birth_data()
            yield event.plain_result("✅ 生日提醒已关闭")
        else:
            yield event.plain_result("❌ 参数只能是【开】或者【关】\n用法：是否通知 开")

    @filter.command("添加生日")
    async def record_birthday(self, event: AstrMessageEvent):
        """用法：添加生日 昵称:农历/国历:月份:日期"""
        raw_text = event.message_str.strip()
        raw_text = raw_text.replace("添加生日","").strip()
        parts = raw_text.split(":")
        if len(parts) != 4:
            yield event.plain_result("❌ 参数格式错误！\n用法：添加生日 昵称:农历/国历:月份:日期\n例：添加生日 阿白:国历:8:15")
            return
        name, date_type, month_str, day_str = parts
        if date_type not in ("农历", "国历"):
            yield event.plain_result("❌ 第二个参数只能填写：农历 或者 国历")
            return
        try:
            month = int(month_str)
            day = int(day_str)
        except ValueError:
            yield event.plain_result("❌ 月份、日期必须是纯数字！")
            return
        try:
            if date_type == "国历":
                datetime(2024, month, day)
            else:
                ZhDate(2024, month, day).to_datetime()
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

    @filter.command("设置时间")
    async def set_notify_time(self, event: AstrMessageEvent):
        raw_text = event.message_str.strip()
        arg = raw_text.replace("设置时间","").strip()
        parts = arg.split(":")
        if len(parts) != 3:
            yield event.plain_result("❌ 参数格式错误！\n格式：设置时间 时:分:秒\n例：设置时间 15:42:00")
            return
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = int(parts[2])
        except ValueError:
            yield event.plain_result("❌ 时、分、秒必须为数字！")
            return
        # 范围校验
        if not (0 <= h <= 23):
            yield event.plain_result("❌ 小时范围必须 0~23")
            return
        if not (0 <= m <= 59):
            yield event.plain_result("❌ 分钟范围必须 0~59")
            return
        if not (0 <= s <= 59):
            yield event.plain_result("❌ 秒范围必须 0~59")
            return
        self.birth_data["notify_time"] = f"{h}:{m}:{s}"
        self.save_birth_data()
        yield event.plain_result(f"✅ 生日提醒定时时间已设置为：{h}时{m}分{s}秒")

    @filter.command("移除生日")
    async def remove_birthday(self, event: AstrMessageEvent):
        raw_text = event.message_str.strip()
        target_name = raw_text.replace("移除生日","").strip()
        if not target_name:
            yield event.plain_result("❌ 需要填写昵称，用法：移除生日 阿白")
            return
        old_len = len(self.birth_data["birthday_list"])
        self.birth_data["birthday_list"] = [item for item in self.birth_data["birthday_list"] if item["name"] != target_name]
        if len(self.birth_data["birthday_list"]) < old_len:
            self.save_birth_data()
            yield event.plain_result(f"✅ 已移除【{target_name}】的生日记录")
        else:
            yield event.plain_result(f"❌ 找不到【{target_name}】的生日记录")

    @filter.command("清理生日")
    async def clear_all_birth(self, event: AstrMessageEvent):
        self.birth_data["birthday_list"] = []
        self.save_birth_data()
        yield event.plain_result("✅ 所有生日记录已清空！")

    @filter.command("生日列表")
    async def show_birth_list(self, event: AstrMessageEvent):
        lst = self.birth_data["birthday_list"]
        if not lst:
            yield event.plain_result("📭 暂无登记的生日记录")
            return
        msg = "📋 已登记生日列表：\n"
        for item in lst:
            msg += f"{item['name']} | {item['type']} {item['month']}月{item['day']}日\n"
        yield event.plain_result(msg)

    @filter.command("设置主播")
    async def set_anchor_qq(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin
        if umo.startswith("group:"):
            yield event.plain_result("❌ 设置主播只能私聊机器人执行！")
            return
        sender_qq = str(event.get_sender_id())
        self.birth_data["anchor_qq"] = sender_qq
        self.birth_data["anchor_umo"] = umo
        self.save_birth_data()
        yield event.plain_result(f"✅ 主播设置完成！QQ：{sender_qq}，当前私聊会话已作为生日通知接收会话。")

    @filter.command("设置管理")
    async def set_manager_qq(self, event: AstrMessageEvent):
        umo = event.unified_msg_origin
        if umo.startswith("group:"):
            yield event.plain_result("❌ 设置管理只能私聊机器人执行！")
            return
        sender_qq = str(event.get_sender_id())
        self.birth_data["manager_qq"] = sender_qq
        self.birth_data["manager_umo"] = umo
        self.save_birth_data()
        yield event.plain_result(f"✅ 管理设置完成！QQ：{sender_qq}，当前私聊会话已作为生日通知接收会话。")

    @filter.command("解绑主播")
    async def unbind_anchor(self, event: AstrMessageEvent):
        sender_qq = str(event.get_sender_id())
        anchor_qq = self.birth_data.get("anchor_qq", "")
        if anchor_qq == "":
            yield event.plain_result("❌ 主播位暂无配置信息，无需解绑")
            return
        if sender_qq != anchor_qq:
            yield event.plain_result("❌ 权限不足！只有主播本人才能执行解绑主播")
            return
        self.birth_data["anchor_umo"] = ""
        self.birth_data["anchor_qq"] = ""
        self.save_birth_data()
        yield event.plain_result("✅ 主播配置已全部清空，可以重新设置。")

    @filter.command("解绑管理")
    async def unbind_manager(self, event: AstrMessageEvent):
        sender_qq = str(event.get_sender_id())
        manager_qq = self.birth_data.get("manager_qq", "")
        if manager_qq == "":
            yield event.plain_result("❌ 管理位暂无配置信息，无需解绑")
            return
        if sender_qq != manager_qq:
            yield event.plain_result("❌ 权限不足！只有管理本人才能执行解绑管理")
            return
        self.birth_data["manager_umo"] = ""
        self.birth_data["manager_qq"] = ""
        self.save_birth_data()
        yield event.plain_result("✅ 管理配置已全部清空，可以重新设置。")

    @filter.command("查看接收")
    async def show_notify_target(self, event: AstrMessageEvent):
        anchor_qq = self.birth_data.get("anchor_qq", "未设置")
        manager_qq = self.birth_data.get("manager_qq", "未设置")
        notify_time = self.birth_data.get("notify_time", "8:0:0")
        if self.birth_data.get("anchor_umo","") != "":
            anchor_bind = "✅已绑定"
        else:
            anchor_bind = "❌未绑定"
        if self.birth_data.get("manager_umo","") != "":
            manager_bind = "✅已绑定"
        else:
            manager_bind = "❌未绑定"
        status = "开启" if self.birth_data.get("notify_enable") else "关闭"
        msg = (
            f"📩生日通知配置\n"
            f"通知状态：{status}\n"
            f"提醒时间：{notify_time}\n"
            f"主播 QQ：{anchor_qq} | {anchor_bind}\n"
            f"管理 QQ：{manager_qq} | {manager_bind}"
        )
        yield event.plain_result(msg)

    @filter.command("立刻通知")
    async def test_notify(self, event: AstrMessageEvent):
        anchor_umo = self.birth_data.get("anchor_umo", "")
        manager_umo = self.birth_data.get("manager_umo", "")
        notify_enable = self.birth_data.get("notify_enable", False)
        if not notify_enable:
            yield event.plain_result("❌ 当前生日通知总开关是关闭状态，无法发送测试消息，请先发送【是否通知 开】")
            return
        if anchor_umo == "" and manager_umo == "":
            yield event.plain_result("❌ 主播、管理会话都未设置，请私聊机器人发送【设置主播】【设置管理】")
            return
        test_msg = "🧪【测试提醒】生日通知功能测试，这条是手动触发的消息，不是定时任务！"
        send_list = []
        try:
            msg_chain = MessageChain([Plain(test_msg)])
            if anchor_umo != "":
                await self.context.send_message(anchor_umo, msg_chain)
                send_list.append("主播")
            if manager_umo != "":
                await self.context.send_message(manager_umo, msg_chain)
        except Exception as e:
            logger.error(f"发送测试通知异常: {e}")
            yield event.plain_result(f"⚠️ 消息发送出错：{str(e)}")
            return
        yield event.plain_result(f"✅ 测试消息已发送给：{','.join(send_list)}")

    async def terminate(self):
        if self.birth_task:
            self.birth_task.cancel()
            try:
                await self.birth_task
            except asyncio.CancelledError:
                logger.info("生日定时任务已取消")
        self.save_birth_data()

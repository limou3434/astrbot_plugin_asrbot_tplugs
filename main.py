from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.event import MessageChain
import aiohttp
import json
import os
from datetime import datetime
import asyncio

@register("bilibili_danmaku", "limou3434", "梦寝兔兔专用群聊插件（每周自定义定时）", "1.3.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.api_endpoint = "http://172.18.168.211:8023/send_danmaku"
        self.max_danmaku_len = 35
        self.data_dir = os.path.join("data", "bilibili_danmaku")
        self.data_path = os.path.join(self.data_dir, "birthday_data.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.birth_data = self.load_birth_data()
        self.birth_task = None
        self.today_alerted = None

    def count_rune(self, s: str) -> int:
        """等价Go utf8.RuneCountInString，统计Unicode字符数"""
        return len(list(s))

    def parse_time_str(self, s: str):
        """解析 HH:MM 为 (hour, minute)，失败返回None"""
        if not s or s.lower() == "null":
            return None
        sp = s.strip().split(":")
        if len(sp) != 2:
            return None
        try:
            h = int(sp[0])
            m = int(sp[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return (h, m)
        except ValueError:
            pass
        return None

    def load_birth_data(self):
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    # 兼容旧版本：如果notify_time是字符串，自动转为整周同时间
                    if "notify_time" in raw and isinstance(raw["notify_time"], str):
                        t = raw["notify_time"]
                        raw["notify_week"] = [t, t, t, t, t, t, t]
                        del raw["notify_time"]
                    return raw
            except Exception as e:
                logger.error(f"生日数据读取失败: {e}")
        # 默认：周一~周日全部 08:00
        return {
            "notify_enable": True,
            "anchor_qq": "",
            "manager_qq": "",
            "anchor_umo": "",
            "manager_umo": "",
            "notify_week": ["8:00", "8:00", "8:00", "8:00", "8:00", "8:00", "8:00"],
            "birthday_list": []
        }

    def save_birth_data(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.birth_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"生日数据保存失败: {e}")

    async def restart_birth_task(self):
        if self.birth_task:
            self.birth_task.cancel()
            try:
                await self.birth_task
            except asyncio.CancelledError:
                logger.info("【生日循环】旧定时任务已取消")
        self.today_alerted = None
        self.birth_task = asyncio.create_task(self.birth_loop())
        logger.info("【生日循环】生日定时任务已重新启动，加载每周定时配置")

    async def initialize(self):
        await self.restart_birth_task()

    async def daily_birthday_check(self):
        if not self.birth_data.get("notify_enable", False):
            logger.info("【生日检查】生日通知总开关关闭，跳过本次定时提醒")
            return
        today = datetime.now()
        birthday_names = []
        # 只国历，直接对比月、日
        for item in self.birth_data["birthday_list"]:
            try:
                if today.month == item["month"] and today.day == item["day"]:
                    birthday_names.append(item["name"])
            except Exception as e:
                logger.warning(f"【生日检查】生日解析异常 {item}：{e}")
        logger.info(f"【生日检查】生日定时检查完成，匹配到今日生日名单：{birthday_names}")
        if not birthday_names:
            logger.info("【生日检查】今日无生日，不发送通知")
            return
        names_str = "、".join(birthday_names)
        msg_text = f"🎂 今日生日提醒！\n{names_str} 今天过生日！"
        logger.info(f"【生日检查】准备发送消息内容：{msg_text}")
        try:
            anchor_umo = self.birth_data.get("anchor_umo", "")
            manager_umo = self.birth_data.get("manager_umo", "")
            msg_chain = MessageChain([Plain(msg_text)])
            if anchor_umo != "":
                await self.context.send_message(anchor_umo, msg_chain)
                logger.info(f"【生日检查】生日提醒发送给主播会话成功")
            else:
                logger.warning("【生日检查】主播umo为空，跳过主播")
            if manager_umo != "":
                await self.context.send_message(manager_umo, msg_chain)
                logger.info(f"【生日检查】生日提醒发送给管理会话成功")
            else:
                logger.warning("【生日检查】管理umo为空，跳过管理")
        except Exception as e:
            logger.error(f"【生日检查】定时生日通知发送失败: {e}")

    async def birth_loop(self):
        week_name = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        while True:
            try:
                now = datetime.now()
                # weekday(): 0=周一，6=周日
                wd = now.weekday()
                week_cfg = self.birth_data.get("notify_week", ["8:00"] * 7)
                today_timestr = week_cfg[wd]
                parsed = self.parse_time_str(today_timestr)

                today_key = (now.year, now.month, now.day)
                # 今天设置为null，直接跳到明天
                if parsed is None:
                    logger.info(f"【生日循环】今天{week_name[wd]}配置为null，不提醒，跳到明天")
                    target = now.replace(day=now.day + 1, hour=0, minute=0, second=0, microsecond=0)
                    sleep_sec = (target - now).total_seconds()
                    await asyncio.sleep(sleep_sec)
                    continue

                h, mi = parsed
                target = datetime(now.year, now.month, now.day, h, mi, 0)

                if self.today_alerted == today_key:
                    target = target.replace(day=now.day + 1)
                    logger.info(f"【生日循环】今日已发送提醒，直接跳到明天 {target.strftime('%Y-%m-%d %H:%M:%S')}")
                    sleep_sec = (target - now).total_seconds()
                    await asyncio.sleep(sleep_sec)
                    continue

                if now > target:
                    await self.daily_birthday_check()
                    self.today_alerted = today_key
                    target = target.replace(day=now.day + 1)
                    logger.info(f"【生日循环】今日提醒完成，切换到明天 {target.strftime('%Y-%m-%d %H:%M:%S')}")

                sleep_sec = (target - now).total_seconds()
                logger.info(f"【生日循环】{week_name[wd]}定时等待 {sleep_sec:.1f}s，目标 {target.strftime('%Y-%m-%d %H:%M:%S')}")
                await asyncio.sleep(sleep_sec)
            except Exception as e:
                logger.error(f"【生日循环】生日定时循环异常，10秒后重试: {e}")
                await asyncio.sleep(10)

    @filter.command("你好")
    async def helloworld(self, event: AstrMessageEvent):
        user_name = event.get_sender_name()
        message_str = event.message_str
        logger.info(message_str)
        yield event.plain_result(f"泥嚎娅~ {user_name}, 沃是兔抛瓦，代号 KUKU 的说!")

    @filter.command("留言")
    async def send(self, event: AstrMessageEvent):
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
                    yield event.plain_result(f"✅ 留言弹幕已提交到直播间的说")
        except aiohttp.ClientConnectionError:
            yield event.plain_result("❌ 笨蛋 kuku 忘记打开某个程序啦！") # 无法连接
        except aiohttp.ClientError:
            yield event.plain_result("❌ 都怪阿 b 的说，发不了啦！") # 网络请求异常，调用弹幕接口失败
        except TimeoutError:
            yield event.plain_result("❌ 额啊啊，请求超时了的说！") # 超时
        except Exception as e:
            yield event.plain_result(f"❌ ？！出现了未知的错误的说：{str(e)}")

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

    @filter.command("设置定时")
    async def set_week_time(self, event: AstrMessageEvent):
        """
        示例：设置周定时 19:30,19:30,19:30,14:30,14:30,14:30,null
        顺序：周一,周二,周三,周四,周五,周六,周日
        null代表当天不提醒
        """
        raw_text = event.message_str.strip()
        arg = raw_text.replace("设置定时","").strip()
        parts = [p.strip() for p in arg.split(",")]
        if len(parts) != 7:
            yield event.plain_result("❌ 必须7个值（周一到周日，逗号隔开）\n例：设置定时 19:30,19:30,19:30,14:30,14:30,14:30,null")
            return
        for p in parts:
            if self.parse_time_str(p) is None and p.lower() != "null":
                yield event.plain_result(f"❌ 无效时间：{p}，只能 HH:MM 或者 null")
                return
        self.birth_data["notify_week"] = parts
        self.save_birth_data()
        await self.restart_birth_task()
        yield event.plain_result(f"✅ 每周定时已保存并重启任务：\n周一:{parts[0]} 周二:{parts[1]} 周三:{parts[2]}\n周四:{parts[3]} 周五:{parts[4]} 周六:{parts[5]}\n周日:{parts[6]}")

    @filter.command("生日列表")
    async def show_birth_list(self, event: AstrMessageEvent):
        lst = self.birth_data["birthday_list"]
        if not lst:
            yield event.plain_result("📭 暂无登记的生日记录")
            return
        msg = "📋 已登记生日列表：\n"
        for item in lst:
            msg += f"{item['name']} | 国历 {item['month']}月{item['day']}日\n"
        yield event.plain_result(msg)

    @filter.command("添加生日")
    async def record_birthday(self, event: AstrMessageEvent):
        """用法：添加生日 昵称:月份:日期"""
        raw_text = event.message_str.strip()
        raw_text = raw_text.replace("添加生日","").strip()
        parts = raw_text.split(":")
        if len(parts) != 3:
            yield event.plain_result("❌ 参数格式错误！\n用法：添加生日 昵称:月份:日期\n例：添加生日 阿白:8:15")
            return
        name, month_str, day_str = parts
        try:
            month = int(month_str)
            day = int(day_str)
        except ValueError:
            yield event.plain_result("❌ 月份、日期必须是纯数字！")
            return
        try:
            # 公历日期合法性校验
            datetime(2024, month, day)
        except Exception:
            yield event.plain_result("❌ 生日日期不合法，请重新输入！")
            return
        exist = False
        for item in self.birth_data["birthday_list"]:
            if item["name"] == name:
                item["month"] = month
                item["day"] = day
                exist = True
                break
        if not exist:
            self.birth_data["birthday_list"].append({
                "name": name,
                "month": month,
                "day": day
            })
        self.save_birth_data()
        yield event.plain_result(f"✅ 生日记录成功！\n{name}｜国历 {month}月{day}日")

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

    @filter.command("查看接收")
    async def show_notify_target(self, event: AstrMessageEvent):
        anchor_qq = self.birth_data.get("anchor_qq", "未设置")
        manager_qq = self.birth_data.get("manager_qq", "未设置")
        week_cfg = self.birth_data.get("notify_week", ["8:00"]*7)
        week_name = ["周一","周二","周三","周四","周五","周六","周日"]
        time_text = "\n".join([f"{week_name[i]}：{week_cfg[i]}" for i in range(7)])

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
            f"⏰每周定时（null=不提醒）：\n{time_text}\n"
            f"主播 QQ：{anchor_qq} | {anchor_bind}\n"
            f"管理 QQ：{manager_qq} | {manager_bind}"
        )
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

    @filter.command("测试通知")
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
        try:
            msg_chain = MessageChain([Plain(test_msg)])
            if anchor_umo != "":
                await self.context.send_message(anchor_umo, msg_chain)
            if manager_umo != "":
                await self.context.send_message(manager_umo, msg_chain)
        except Exception as e:
            logger.error(f"发送测试通知异常: {e}")
            yield event.plain_result(f"⚠️ 消息发送出错：{str(e)}")
            return
        yield event.plain_result(f"✅ 测试消息已发送")

    @filter.command("检查生日")
    async def manual_check_birthday(self, event: AstrMessageEvent):
        yield event.plain_result("🔍 开始执行生日扫描+发送逻辑，请查看日志！")
        await self.daily_birthday_check()

    async def terminate(self):
        if self.birth_task:
            self.birth_task.cancel()
            try:
                await self.birth_task
            except asyncio.CancelledError:
                logger.info("生日定时任务已取消")
        self.save_birth_data()

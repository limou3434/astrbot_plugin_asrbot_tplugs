from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import aiohttp

@register("bilibili_danmaku", "limou3434", "将QQ留言转为B站直播间弹幕，调用Go后端接口", "1.0.0")
class MyPlugin(Star): # 插件需要继承 Star 类，具体的处理函数 Handler 在插件类中定义，如这里的 helloworld 函数
    def __init__(self, context: Context): # Context 类用于插件与 AstrBot Core 交互，可以由此调用 AstrBot Core 提供的各种 API
        super().__init__(context)
        self.api_endpoint = "http://172.18.167.28:8023/send_danmaku" # Go 弹幕接口内网地址
        self.max_danmaku_len = 30 # 和 Go 服务保持一致：【sender】msg 拼接，总上限 30 字符
    
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
    async def send(self, event: AstrMessageEvent):
        """这是一个哔哩哔哩留言指令，可以把 QQ 消息转化为弹幕发送到某个 b 站 up 主的直播间中""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
        # 获取发送者的一些信息
        user_name = event.get_sender_name() # 获取发送者 QQ 昵称
        message_str = event.message_str # 用户发的纯文本消息字符串
        message_chain = event.get_messages() # 用户所发的消息的消息链 from astrbot.api.message_components import *
        logger.info(message_chain)
       
        # 移除指令前缀 "/留言"，拿到真正用户留言内容
        cmd_prefix = "/留言"
        content = message_str.strip()

        if content.startswith(cmd_prefix):
            content = content[len(cmd_prefix):].strip()
       
        if not content:
            yield event.plain_result("❌ 啊啊啊留言内容不能为空哇！用法：/留言 你想说的话的说（认真）")
            return

        # 昵称裁剪：超过 5 字自动截断为前 5 个字符
        short_name = user_name[:5]
        max_total_char = 35  # 整体弹幕最多 35 字符，和 Go 保持一致
        bracket_len = 2 # 【】两个符号，各算 1 字符
        short_name_len = len(short_name)
        used_len = short_name_len + bracket_len
        remain_for_msg = max_total_char - used_len

        if remain_for_msg <= 0:
            yield event.plain_result(f"❌ 昵称裁剪后【{short_name}】空间不足，无法附加留言发送弹幕")
            return

        if len(content) > remain_for_msg:
            yield event.plain_result(
                f"❌ 留言过长！\n昵称已自动裁剪为【{short_name}】，剩余可写{remain_for_msg}字符\n当前留言长度：{len(content)}"
            )
            return

        # 拼接最终弹幕文本
        full_text = f"【{short_name}】{content}"
        # 传给Go接口的sender使用裁剪后的昵称
        try:
            params = {
                "sender": short_name,
                "msg": content
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_endpoint,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp_text = await resp.text()
                    yield event.plain_result(f"✅ 留言已提交")
        except aiohttp.ClientConnectionError:
            yield event.plain_result("❌ 无法连接弹幕后端，请检查 Go 服务是否启动，确认 172.18.167.28:8023 网络连通")
        except aiohttp.ClientError:
            yield event.plain_result("❌ 网络请求异常，调用弹幕接口失败")
        except TimeoutError:
            yield event.plain_result("❌ 请求超时，Go 服务响应超时")
        except Exception as e:
            # 兜底捕获，避免插件崩溃
            yield event.plain_result(f"❌ 未知错误：{str(e)}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

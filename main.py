from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import aiohttp

def count_rune(s: str) -> int:
    """等价Go utf8.RuneCountInString，统计Unicode字符数"""
    return len(list(s))

@register("bilibili_danmaku", "limou3434", "将QQ留言转为B站直播间弹幕，调用Go后端接口", "1.0.0")
class MyPlugin(Star): # 插件需要继承 Star 类，具体的处理函数 Handler 在插件类中定义，如这里的 helloworld 函数
    def __init__(self, context: Context): # Context 类用于插件与 AstrBot Core 交互，可以由此调用 AstrBot Core 提供的各种 API
        super().__init__(context)
        self.api_endpoint = "http://172.18.167.28:8023/send_danmaku" # Go 弹幕接口内网地址
        self.max_danmaku_len = 35 # 和 Go 服务保持一致：【sender】msg 拼接，总上限 30 字符
    
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
                    yield event.plain_result(f"✅ 留言弹幕已提交，预览：{full_danmaku}")
        except aiohttp.ClientConnectionError:
            yield event.plain_result("❌ 无法连接弹幕后端，请检查 Go 服务是否启动，确认 172.18.167.28:8023 网络连通")
        except aiohttp.ClientError:
            yield event.plain_result("❌ 网络请求异常，调用弹幕接口失败")
        except TimeoutError:
            yield event.plain_result("❌ 请求超时，Go 服务响应超时")
        except Exception as e:
            yield event.plain_result(f"❌ 未知错误：{str(e)}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

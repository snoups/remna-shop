from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup
from aiogram_dialog.api.entities import NewMessage, OldMessage
from aiogram_dialog.manager.message_manager import SEND_METHODS
from aiogram_dialog.manager.message_manager import MessageManager as MessageManagerProtocol

from src.telegram.widgets import extract_color, extract_tg_emoji


def _process_keyboard(markup: object) -> None:
    if isinstance(markup, InlineKeyboardMarkup):
        for row in markup.inline_keyboard:
            for btn in row:
                text, emoji_id = extract_tg_emoji(btn.text)
                text, color = extract_color(text)
                btn.text = text
                if color is not None:
                    btn.style = color
                if emoji_id and not btn.icon_custom_emoji_id:
                    btn.icon_custom_emoji_id = emoji_id
    elif isinstance(markup, ReplyKeyboardMarkup):
        for kb_row in markup.keyboard:
            for kb_btn in kb_row:
                text, _ = extract_tg_emoji(kb_btn.text)
                kb_btn.text, _ = extract_color(text)


class MessageManager(MessageManagerProtocol):
    async def show_message(
        self,
        bot: Bot,
        new_message: NewMessage,
        old_message: OldMessage | None,
    ) -> OldMessage:
        _process_keyboard(new_message.reply_markup)
        return await super().show_message(bot, new_message, old_message)

    async def send_text(self, bot: Bot, new_message: NewMessage) -> Message:
        return await bot.send_message(
            new_message.chat.id,
            text=new_message.text,  # type: ignore[arg-type]
            message_thread_id=new_message.thread_id,
            business_connection_id=new_message.business_connection_id,
            reply_markup=new_message.reply_markup,
            parse_mode=new_message.parse_mode,
            link_preview_options=new_message.link_preview_options,
            message_effect_id=getattr(new_message, "message_effect_id", None),
        )

    async def send_media(self, bot: Bot, new_message: NewMessage) -> Message:
        method = getattr(bot, SEND_METHODS[new_message.media.type], None)  # type: ignore[union-attr]

        if not method:
            raise ValueError(
                f"ContentType {new_message.media.type} is not supported",  # type: ignore[union-attr]
            )

        return await method(  # type: ignore[no-any-return]
            new_message.chat.id,
            await self.get_media_source(new_message.media, bot),  # type: ignore[arg-type]
            message_thread_id=new_message.thread_id,
            business_connection_id=new_message.business_connection_id,
            caption=new_message.text,
            reply_markup=new_message.reply_markup,
            parse_mode=new_message.parse_mode,
            message_effect_id=getattr(new_message, "message_effect_id", None),
            **new_message.media.kwargs,  # type: ignore[union-attr]
        )

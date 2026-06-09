import os
from botbuilder.core import ActivityHandler, TurnContext, BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity


class TeamsBot(ActivityHandler):
    def __init__(self, response_processor, db):
        self._response_processor = response_processor
        self._db = db

    async def on_message_activity(self, turn_context: TurnContext):
        user_message = (turn_context.activity.text or "").strip()

        # Strip @mention text that Teams prepends in channel conversations
        if turn_context.activity.entities:
            for entity in (turn_context.activity.entities or []):
                mention_text = entity.get("text", "") if isinstance(entity, dict) else getattr(entity, "text", "")
                if mention_text:
                    user_message = user_message.replace(mention_text, "").strip()

        if not user_message:
            return

        from_prop = turn_context.activity.from_property
        teams_oid = getattr(from_prop, "aad_object_id", None) or from_prop.id
        display_name = from_prop.name or "Teams User"
        teams_conv_id = turn_context.activity.conversation.id

        db_user = self._db.get_or_create_teams_user(teams_oid, display_name)
        user_id = db_user["id"]
        conv = self._db.get_or_create_teams_conversation(user_id, teams_conv_id)
        conv_id = conv["id"]

        conv_history = self._db.get_conversation_messages(conv_id, user_id)
        self._db.add_message(conv_id, "user", user_message, "text")

        try:
            processed = await self._response_processor.process_message(
                user_message, display_name, conv_history
            )
        except Exception as e:
            print(f"[Teams] process_message error: {e}")
            processed = None

        if processed:
            reply_text = processed.message
            self._db.add_message(conv_id, "assistant", reply_text, processed.response_type)
        else:
            reply_text = "ขออภัย ไม่สามารถประมวลผลได้ในขณะนี้ กรุณาลองใหม่อีกครั้งนะครับ"
            self._db.add_message(conv_id, "assistant", reply_text, "text")

        await turn_context.send_activity(reply_text)

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    "สวัสดีครับ น้อง I-SAVE Chatbot พร้อมให้บริการแล้วนะครับ พิมพ์คำถามได้เลยครับ"
                )


def create_teams_adapter() -> BotFrameworkAdapter:
    settings = BotFrameworkAdapterSettings(
        app_id=os.environ.get("MicrosoftAppId", ""),
        app_password=os.environ.get("MicrosoftAppPassword", ""),
    )
    return BotFrameworkAdapter(settings)

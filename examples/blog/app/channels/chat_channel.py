from app.channels.application_channel import ApplicationChannel
from app.validators.chat_message_validator import ChatMessageValidator
from bingo import BingoChannelError


class ChatChannel(ApplicationChannel):
    async def subscribed(self):
        room = self.params.get("room")
        if room != "lobby":
            raise BingoChannelError("The demo only provides the lobby room.")

        self.room = room
        await self.stream(room)

    async def received(self, data: dict):
        message = ChatMessageValidator(data).validate()
        await type(self).broadcast(self.room, "message", **message)

from app.controllers.application_controller import ApplicationController


class ChatController(ApplicationController):
    async def show(self):
        return self.render("chat/show.html")

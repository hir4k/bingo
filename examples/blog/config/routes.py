from bingo import Router

routes = Router()

routes.resources("/posts")
routes.get("/chat", "ChatController.show")

from app.controllers.posts_controller import PostsController

from bingo import Router

routes = Router()

routes.resources("/posts", PostsController)

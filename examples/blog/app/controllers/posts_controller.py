from app.controllers.application_controller import ApplicationController
from app.models.post import Post
from app.validators.post_create_validator import PostCreateValidator
from app.validators.post_update_validator import PostUpdateValidator


class PostsController(ApplicationController):
    async def index(self):
        posts = await Post.all()
        return self.render("posts/index", posts=posts)

    async def show(self):
        post = await Post.find_or_fail(self.params["id"])
        return self.render("posts/show", post=post)

    async def new(self):
        validator = self.validation or PostCreateValidator()
        return self.render(
            "posts/new.html",
            validator=validator,
        )

    async def create(self):
        data = PostCreateValidator(self.request.data).validate()
        post = await Post.create(**data)
        if self.request.format == "json":
            return self.render(
                "posts/show",
                post=post,
                status=201,
            )

        return self.redirect(f"/posts/{post.id}")

    async def edit(self):
        post = await Post.find_or_fail(self.params["id"])
        validator = self.validation or PostUpdateValidator(post.to_dict())
        return self.render(
            "posts/edit.html",
            post=post,
            validator=validator,
        )

    async def update(self):
        post = await Post.find_or_fail(self.params["id"])
        data = PostUpdateValidator(self.request.data).validate()
        post.fill(**data)
        await post.save()
        if self.request.format == "json":
            return self.render(
                "posts/show",
                post=post,
            )

        return self.redirect(f"/posts/{post.id}")

    async def destroy(self):
        post = await Post.find_or_fail(self.params["id"])
        await post.delete()
        if self.request.format == "json":
            return self.json({"deleted": True})

        return self.redirect("/posts")

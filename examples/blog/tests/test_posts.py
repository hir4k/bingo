def test_posts_resource_was_generated():
    from pathlib import Path

    from app.controllers.posts_controller import PostsController
    from app.models.post import Post

    assert Post.__tablename__ == "posts"
    assert PostsController.__name__ == "PostsController"
    assert Path("app/views/posts/index.bjson").is_file()
    assert Path("app/views/posts/show.bjson").is_file()

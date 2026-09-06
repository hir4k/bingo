from bingo.db.naming import pluralize, singularize, snake_case


def test_conventional_names_cover_common_resource_words():
    assert snake_case("BlogPost") == "blog_post"
    assert pluralize("post") == "posts"
    assert pluralize("category") == "categories"
    assert singularize("categories") == "category"

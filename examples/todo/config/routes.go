package config

import (
	"example.com/todo/controllers"
	"github.com/hir4k/bingo"
)

func RegisterRoutes(root *bingo.Router) {
	root.Get("/todos", controllers.TodosIndex, "todos.index")
	root.Get("/todos/new", controllers.TodosNew, "todos.new")
	root.Get("/todos/:id", controllers.TodosShow, "todos.show")
	root.Get("/todos/:id/edit", controllers.TodosEdit, "todos.edit")
	root.Post("/todos", controllers.TodosCreate, "todos.create")
	root.Put("/todos/:id", controllers.TodosUpdate, "todos.replace")
	root.Patch("/todos/:id", controllers.TodosUpdate, "todos.update")
	root.Delete("/todos/:id", controllers.TodosDestroy, "todos.destroy")
}

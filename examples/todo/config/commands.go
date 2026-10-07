package config

import (
	"example.com/todo/commands"
	"github.com/hir4k/bingo"
)

func RegisterCommands(registry *bingo.Commands) {
	registry.Register("todo_count", "Count todos in the current environment", commands.TodoCount)
}

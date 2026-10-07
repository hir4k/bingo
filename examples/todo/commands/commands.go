package commands

import (
	"example.com/todo/models"
	"fmt"
	"github.com/hir4k/bingo"
)

func TodoCount(ctx *bingo.CommandContext) error {
	if len(ctx.Args) != 0 {
		return fmt.Errorf("usage: todo_count")
	}
	var count int64
	if err := ctx.DB.Model(&models.Todo{}).Count(&count).Error; err != nil {
		return err
	}
	_, err := fmt.Fprintln(ctx.Out, count)
	return err
}

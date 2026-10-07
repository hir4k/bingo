// The application owns its assets and registration; Bingo dispatches runtime commands.
package main

import (
	"embed"
	"log"
	"os"

	"example.com/todo/config"
	"github.com/hir4k/bingo"
)

//go:embed views database/migrations
var assets embed.FS

func main() {
	var app *bingo.App = bingo.New()
	app.Views(assets)
	app.Database(config.Database)
	app.Routes(config.RegisterRoutes)
	app.Commands(config.RegisterCommands)
	var address string = os.Getenv("BINGO_ADDR")
	if address == "" {
		address = ":8080"
	}
	if err := app.Run(address); err != nil {
		log.Fatal(err)
	}
}

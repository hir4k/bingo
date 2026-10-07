package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/hir4k/bingo"
	"github.com/hir4k/bingo/internal/project"
)

func execute(arguments []string, output io.Writer, errorOutput io.Writer) int {
	var command string = arguments[0]
	if command == "version" {
		if len(arguments) != 1 {
			commandHelp(command, errorOutput)
			return 2
		}
		fmt.Fprintln(output, bingo.Version)
		return 0
	}
	var flags *flag.FlagSet = flag.NewFlagSet(command, flag.ContinueOnError)
	flags.SetOutput(errorOutput)
	var app *string = flags.String("app", ".", "application directory")
	var environment *string
	var address *string
	var args []string = arguments[1:]
	var kind string
	if command == "generate" || command == "db" {
		if len(args) > 0 && (args[0] == "--help" || args[0] == "-h") {
			commandHelp(command, output)
			return 0
		}
		if len(args) == 0 {
			commandHelp(command, errorOutput)
			return 2
		}
		kind = args[0]
		args = args[1:]
	}
	if command == "db" {
		environment = flags.String("env", "development", "database environment")
	}
	if command == "serve" {
		address = flags.String("addr", ":8080", "listen address")
	}
	if err := flags.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	var root string
	var err error
	root, err = filepath.Abs(*app)
	if err != nil {
		fmt.Fprintln(errorOutput, err)
		return 1
	}
	if _, err = os.Stat(filepath.Join(root, "config", "database.go")); err != nil {
		fmt.Fprintln(errorOutput, "Run from a Bingo project or pass --app PATH.")
		return 1
	}
	var ctx context.Context
	var cancel context.CancelFunc
	ctx, cancel = signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	switch command {
	case "generate":
		if flags.NArg() == 0 {
			commandHelp(command, errorOutput)
			return 2
		}
		var name string = flags.Arg(0)
		switch kind {
		case "model":
			err = project.GenerateModel(root, name, flags.Args()[1:])
		case "migration":
			var inferred bool
			inferred, err = project.GenerateMigration(root, name, flags.Args()[1:])
			if err == nil && !inferred {
				fmt.Fprintln(output, "Created migration skeleton. Replace its SQL guard before migrating.")
			}
		case "controller":
			if flags.NArg() != 1 {
				commandHelp(command, errorOutput)
				return 2
			}
			err = project.GenerateController(root, name)
			if err == nil {
				fmt.Fprintln(output, "Register its functions in config/routes.go with router.Get/Post/Put/Patch/Delete.")
			}
		default:
			commandHelp(command, errorOutput)
			return 2
		}
		if err == nil {
			fmt.Fprintln(output, "Generated", kind, name)
		}
	case "db":
		if flags.NArg() != 0 {
			commandHelp(command, errorOutput)
			return 2
		}
		switch kind {
		case "migrate", "rollback", "status", "version":
		default:
			commandHelp(command, errorOutput)
			return 2
		}
		err = project.RunCommand(ctx, root, []string{"db", kind, "--env", *environment}, os.Stdin, output, errorOutput)
	case "build":
		if flags.NArg() != 0 {
			commandHelp(command, errorOutput)
			return 2
		}
		var binary string = "app"
		if os.PathSeparator == '\\' {
			binary += ".exe"
		}
		err = project.Build(ctx, root, filepath.Join(root, "bin", binary), false, output, errorOutput)
		if err == nil {
			fmt.Fprintln(output, "Built production executable: bin/"+binary)
		}
	case "serve":
		if flags.NArg() != 0 {
			commandHelp(command, errorOutput)
			return 2
		}
		err = project.Serve(ctx, root, *address, output, errorOutput)
	default:
		usage(errorOutput)
		return 2
	}
	if err != nil {
		fmt.Fprintln(errorOutput, err)
		return 1
	}
	return 0
}

func commandHelp(command string, output io.Writer) {
	switch command {
	case "init":
		fmt.Fprintln(output, "bingo init [--module MODULE] [--framework PATH] [DIRECTORY]")
	case "generate":
		fmt.Fprintln(output, "bingo generate controller|model|migration [--app PATH] NAME [field:type ...]")
	case "db":
		fmt.Fprintln(output, "bingo db migrate|rollback|status|version [--app PATH] [--env development|test|production]")
	case "serve":
		fmt.Fprintln(output, "bingo serve [--app PATH] [--addr :8080] (development only)")
	case "build":
		fmt.Fprintln(output, "bingo build [--app PATH] (production only)")
	case "version":
		fmt.Fprintln(output, "bingo version")
	default:
		usage(output)
	}
}

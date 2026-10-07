package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/hir4k/bingo/internal/project"
)

// Only --app belongs to the development tool. Leave custom flags/arguments for
// the application's handler instead of guessing their meanings in the CLI.
func delegate(arguments []string, output io.Writer, errorOutput io.Writer) int {
	var directory string = "."
	var args []string = []string{arguments[0]}
	var remaining []string = arguments[1:]
	for index := 0; index < len(remaining); index++ {
		var argument string = remaining[index]
		if argument == "--" {
			args = append(args, remaining[index:]...)
			break
		}
		if argument == "--app" {
			index++
			if index == len(remaining) {
				fmt.Fprintln(errorOutput, "--app requires a directory")
				return 2
			}
			directory = remaining[index]
			continue
		}
		if strings.HasPrefix(argument, "--app=") {
			directory = strings.TrimPrefix(argument, "--app=")
			continue
		}
		args = append(args, argument)
	}
	var root string
	var err error
	root, err = filepath.Abs(directory)
	if err != nil {
		fmt.Fprintln(errorOutput, err)
		return 1
	}
	if _, err = os.Stat(filepath.Join(root, "config/database.go")); err != nil {
		fmt.Fprintf(errorOutput, "Unknown development command %q; run custom commands from a Bingo app or use --app PATH.\n", arguments[0])
		return 2
	}
	var ctx context.Context
	var cancel context.CancelFunc
	ctx, cancel = signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	err = project.RunCommand(ctx, root, args, os.Stdin, output, errorOutput)
	if err != nil {
		fmt.Fprintln(errorOutput, err)
		return 1
	}
	return 0
}

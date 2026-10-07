// Command bingo creates a runnable application with bingo init.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

	"github.com/hir4k/bingo/internal/project"
)

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

func run(arguments []string, output io.Writer, errorOutput io.Writer) int {
	if len(arguments) == 0 {
		usage(errorOutput)
		return 2
	}
	if arguments[0] == "help" || arguments[0] == "--help" || arguments[0] == "-h" {
		if len(arguments) > 1 {
			switch arguments[1] {
			case "init", "generate", "db", "serve", "build", "version":
				commandHelp(arguments[1], output)
				return 0
			default:
				return delegate(arguments, output, errorOutput)
			}
		}
		usage(output)
		if _, err := os.Stat("config/database.go"); err == nil {
			return delegate([]string{"help"}, output, errorOutput)
		}
		return 0
	}
	if arguments[0] != "init" {
		switch arguments[0] {
		case "generate", "db", "serve", "build", "version":
			return execute(arguments, output, errorOutput)
		}
		return delegate(arguments, output, errorOutput)
	}
	var flags *flag.FlagSet = flag.NewFlagSet("init", flag.ContinueOnError)
	flags.SetOutput(errorOutput)
	var module *string = flags.String("module", "", "Go module path (default: example.com/directory-name)")
	var framework *string = flags.String("framework", localFramework(), "local Bingo module directory")
	if err := flags.Parse(arguments[1:]); err != nil {
		if err == flag.ErrHelp {
			return 0
		}
		return 2
	}
	if flags.NArg() > 1 {
		usage(errorOutput)
		return 2
	}
	var destination string = "."
	if flags.NArg() == 1 {
		destination = flags.Arg(0)
	}
	var absolute string
	var err error
	absolute, err = filepath.Abs(destination)
	if err != nil {
		fmt.Fprintln(errorOutput, err)
		return 1
	}
	if *module == "" {
		var name string = strings.ToLower(filepath.Base(absolute))
		var unsafeCharacters *regexp.Regexp = regexp.MustCompile(`[^a-z0-9_-]+`)
		name = strings.Trim(unsafeCharacters.ReplaceAllString(name, "-"), "-")
		if name == "" {
			name = "bingoapp"
		}
		*module = "example.com/" + name
	}
	if *framework == "" {
		fmt.Fprintln(errorOutput, "Cannot locate Bingo checkout; pass --framework PATH.")
		return 1
	}
	err = project.Init(destination, *module, *framework)
	if err != nil {
		fmt.Fprintln(errorOutput, err)
		return 1
	}
	fmt.Fprintf(output, "Created Bingo project in %s\nRun bingo db migrate, then bingo serve from that directory.\n", absolute)
	return 0
}

// The local checkout has no published version yet. Source location lets a locally
// built/installed CLI scaffold it offline; --framework supports relocated builds.
func localFramework() string {
	var source string
	var found bool
	_, source, _, found = runtime.Caller(0)
	if !found || !filepath.IsAbs(source) {
		return ""
	}
	return filepath.Clean(filepath.Join(filepath.Dir(source), "../.."))
}

func usage(output io.Writer) {
	fmt.Fprintln(output, "Bingo commands:")
	for _, command := range []string{"init", "serve", "build", "generate", "db", "version"} {
		commandHelp(command, output)
	}
	fmt.Fprintln(output, "bingo help [command]")
}

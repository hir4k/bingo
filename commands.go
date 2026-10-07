package bingo

import (
	"context"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"

	"gorm.io/gorm"
)

// CommandContext carries process cancellation, a context-bound native GORM
// session, arguments, and streams. Commands return errors rather than exiting so
// cleanup happens before the executable reports a nonzero status.
type CommandContext struct {
	Context     context.Context
	DB          *gorm.DB
	Args        []string
	In          io.Reader
	Out         io.Writer
	Err         io.Writer
	Environment string
}
type CommandHandler func(*CommandContext) error
type command struct {
	description string
	handler     CommandHandler
}
type Commands struct {
	entries map[string]command
	frozen  bool
}

var commandName = regexp.MustCompile(`^[a-z][a-z0-9]*(_[a-z0-9]+)*$`)

func reservedCommand(name string) bool {
	switch name {
	case "db", "help", "version", "init", "generate", "serve", "build":
		return true
	default:
		return false
	}
}

// Register is explicit: importing a package never registers commands as a side
// effect. Reserved names and duplicate names fail during application setup.
func (c *Commands) Register(name string, description string, handler CommandHandler) {
	if c.frozen {
		panic("bingo: commands are frozen after execution starts")
	}
	if !commandName.MatchString(name) {
		panic("bingo: command names must use lowercase snake_case: " + name)
	}
	if reservedCommand(name) {
		panic("bingo: reserved command " + name)
	}
	if description == "" || handler == nil {
		panic("bingo: command requires a description and handler: " + name)
	}
	if _, exists := c.entries[name]; exists {
		panic("bingo: duplicate command " + name)
	}
	if c.entries == nil {
		c.entries = make(map[string]command)
	}
	c.entries[name] = command{description: description, handler: handler}
}

func (a *App) Commands(register func(*Commands)) {
	if register == nil {
		panic("bingo: command registration cannot be nil")
	}
	register(a.commands)
}

func (a *App) environment() string {
	if a.development {
		return "development"
	}
	return "production"
}

// Execute is shared by application binaries and the development CLI delegation.
// No arguments to Run starts the server; command arguments never start a listener.
// Help/version do not open a database or require application files on disk.
func (a *App) Execute(ctx context.Context, args []string, input io.Reader, output io.Writer, errorOutput io.Writer) error {
	a.commands.frozen = true
	if len(args) == 0 {
		return fmt.Errorf("expected an application command")
	}
	var name string = args[0]
	switch name {
	case "help", "--help", "-h":
		if len(args) > 2 {
			return fmt.Errorf("usage: app help [command]")
		}
		if len(args) == 2 {
			return a.commandHelp(args[1], output)
		}
		fmt.Fprintln(output, "Run without arguments to start the server.")
		fmt.Fprintln(output, "db migrate|rollback|status|version [--env ENV]")
		fmt.Fprintln(output, "version\nhelp [command]")
		var names []string
		for name := range a.commands.entries {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			fmt.Fprintf(output, "%s\t%s\n", name, a.commands.entries[name].description)
		}
		return nil
	case "version":
		if len(args) != 1 {
			return fmt.Errorf("usage: app version")
		}
		_, err := fmt.Fprintln(output, Version)
		return err
	case "db":
		return a.databaseCommand(ctx, args[1:], output, errorOutput)
	}
	var registered command
	var exists bool
	registered, exists = a.commands.entries[name]
	if !exists {
		return fmt.Errorf("unknown application command %q; use help", name)
	}
	if len(args) == 2 && (args[1] == "--help" || args[1] == "-h") {
		return a.commandHelp(name, output)
	}
	var config DatabaseConfig
	var err error
	config, err = a.DatabaseSettings(a.environment())
	if err != nil {
		return err
	}
	var db *gorm.DB
	db, err = OpenDatabase(config)
	if err != nil {
		return err
	}
	pool, err := db.DB()
	if err != nil {
		return err
	}
	defer pool.Close()
	var commandContext *CommandContext = &CommandContext{Context: ctx, DB: db.WithContext(ctx), Args: append([]string(nil), args[1:]...), In: input, Out: output, Err: errorOutput, Environment: a.environment()}
	return registered.handler(commandContext)
}

func (a *App) commandHelp(name string, output io.Writer) error {
	switch name {
	case "db":
		fmt.Fprintln(output, "db migrate|rollback|status|version [--env development|test|production]")
		return nil
	case "version":
		fmt.Fprintln(output, "version")
		return nil
	case "help":
		fmt.Fprintln(output, "help [command]")
		return nil
	}
	if registered, exists := a.commands.entries[name]; exists {
		fmt.Fprintf(output, "%s: %s\n", name, registered.description)
		return nil
	}
	return fmt.Errorf("unknown application command %q", name)
}

func (a *App) databaseCommand(ctx context.Context, args []string, output io.Writer, errorOutput io.Writer) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: db migrate|rollback|status|version")
	}
	if args[0] == "--help" || args[0] == "-h" {
		return a.commandHelp("db", output)
	}
	var operation string = args[0]
	switch operation {
	case "migrate", "rollback", "status", "version":
	default:
		return fmt.Errorf("unknown database command %q", operation)
	}
	var flags *flag.FlagSet = flag.NewFlagSet("db "+operation, flag.ContinueOnError)
	flags.SetOutput(errorOutput)
	var environment *string = flags.String("env", a.environment(), "database environment")
	if err := flags.Parse(args[1:]); err != nil {
		if err == flag.ErrHelp {
			return nil
		}
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected database command arguments")
	}
	var config DatabaseConfig
	var err error
	config, err = a.DatabaseSettings(*environment)
	if err != nil {
		return err
	}
	var migrations fs.FS
	if a.development || a.views == nil {
		migrations = os.DirFS(filepath.Join(a.Directory, "database/migrations"))
	} else {
		migrations, err = fs.Sub(a.views, "database/migrations")
		if err != nil {
			return fmt.Errorf("embedded migrations unavailable: %w", err)
		}
	}
	return runMigrations(ctx, config, migrations, operation, output)
}

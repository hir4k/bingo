package bingo

import (
	"context"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"gorm.io/gorm"
)

// BuildMode is set by the CLI through the Go linker's -X flag. Direct builds
// default to production; only bingo serve builds a development executable.
var BuildMode string = "production"

const Version string = "0.7.0"

// App owns the connection, routing tree, assets, and server lifetime. DB is native
// GORM; handler DB sessions inherit request cancellation without a CRUD wrapper.
type App struct {
	DB          *gorm.DB
	root        *Router
	views       fs.FS
	development bool
	Directory   string
	database    func(string) (DatabaseConfig, error)
	commands    *Commands
	jobs        *Jobs
}

func New() *App {
	var directory string = os.Getenv("BINGO_APP_DIR")
	if directory == "" {
		directory = "."
	}
	var app *App = &App{Directory: directory, commands: &Commands{entries: make(map[string]command)}, development: BuildMode == "development"}
	app.jobs = &Jobs{handlers: make(map[string]JobHandler)}
	app.root = &Router{state: &routingState{app: app, names: make(map[string]*route)}}
	return app
}

// Views supplies embedded views and migrations in production.
// Development reads templates from
// disk on every render, so a CLI restart is unnecessary for template edits.
func (a *App) Views(assets fs.FS) { a.views = assets }
func (a *App) Routes(register func(*Router)) {
	if register == nil {
		panic("bingo: route registration cannot be nil")
	}
	a.root.mutable()
	register(a.root)
}

func (a *App) Handler() http.Handler {
	a.jobs.frozen = true
	var handler http.Handler = a.root.handler()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writer := &responseState{ResponseWriter: w}
		defer func() {
			if value := recover(); value != nil {
				log.Printf("bingo: panic: %v", value)
				if writer.committed {
					return
				}
				var message string = "Internal server error"
				if a.development {
					message = fmt.Sprintf("Panic: %v", value)
				}
				http.Error(writer, message, http.StatusInternalServerError)
			}
		}()
		handler.ServeHTTP(writer, r)
	})
}

// Run dispatches process arguments as commands, or starts the server when there
// are no arguments. Startup never migrates. Signals cancel commands or allow
// in-flight requests ten seconds to finish before closing the database.
func (a *App) Run(address string) error {
	if len(os.Args) > 1 {
		var ctx context.Context
		var stop context.CancelFunc
		ctx, stop = signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		return a.Execute(ctx, os.Args[1:], os.Stdin, os.Stdout, os.Stderr)
	}
	return a.serve(address)
}

func (a *App) serve(address string) error {
	a.commands.frozen = true
	var environment string = "production"
	if a.development {
		environment = "development"
	}
	var config DatabaseConfig
	var err error
	config, err = a.DatabaseSettings(environment)
	if err != nil {
		return err
	}
	a.DB, err = OpenDatabase(config)
	if err != nil {
		return err
	}
	var pool, poolError = a.DB.DB()
	if poolError != nil {
		return poolError
	}
	defer pool.Close()
	var server http.Server = http.Server{Addr: address, Handler: a.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second}
	var signalContext context.Context
	var stop context.CancelFunc
	signalContext, stop = signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	var finished chan struct{} = make(chan struct{})
	var shutdownDone chan struct{} = make(chan struct{})
	go func() {
		defer close(shutdownDone)
		select {
		case <-signalContext.Done():
		case <-finished:
			return
		}
		var ctx context.Context
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if shutdownError := server.Shutdown(ctx); shutdownError != nil {
			_ = server.Close()
		}
	}()
	log.Printf("Bingo %s listening on %s (%s)", Version, address, environment)
	err = server.ListenAndServe()
	close(finished)
	<-shutdownDone
	if err == http.ErrServerClosed {
		return nil
	}
	return err
}

# Bingo

A Bingo application with function handlers, explicit routes, native GORM, SQLite,
and Goose SQL migrations.

```sh
go install ./cmd/bingo
bingo new myapp
cd myapp
bingo serve
```

new creates an empty application in a new or empty directory. Use bingo new .
to create it in the current empty folder. An explicit name or . is required.
There are no default handlers, views, models, jobs, or custom commands;
only the framework queue infrastructure migration is included;
empty directories contain .keep files. Config files include commented setup
examples and generator commands. Until Bingo is published, generated
modules reference the local checkout. --framework PATH selects that checkout.
If another executable named bingo precedes Go's binary on PATH, use
"$(go env GOPATH)/bin/bingo" or put Go's bin directory first.

For the separate demo, run bingo db migrate --app examples/todo, then
bingo serve --app examples/todo. Open [the todo collection](http://localhost:8080/todos). HTML and JSON are available
at /todos, /todos.json, /todos/1, and /todos/1.json. POST /todos creates, PATCH/PUT
/todos/1 updates, and DELETE /todos/1 removes. Writes require application/json.

main.go is the only root Go source. config/routes.go registers handlers:

```go
root.Get("/todos", controllers.TodosIndex, "todos.index")
root.Get("/todos/:id", controllers.TodosShow, "todos.show")
```

Handlers accept *bingo.Context and return error. DB is native GORM already bound
to the request context; Params contains named strings. Return database errors or
bingo.HTTPError(status, message) for centralized error handling.

```go
func TodosIndex(c *bingo.Context) error {
    var todos []models.Todo
    if err := c.DB.Order("id").Find(&todos).Error; err != nil {
        return err
    }
    return c.Render("todos/index", todos)
}
```

Get/Post/Put/Patch/Delete declare endpoints explicitly. Group only handles URL
prefixes and middleware. Use must precede routes/groups in each scope. Named routes
are optional and never inherit names. c.URL("todos.show", map[string]string{"id":"1"})
returns an escaped URL or error. HTML templates use {{url "todos.show" "id" .ID}}.

Views use Go templates named index.html.ego and index.json.ego. Render paths remain
explicit without extensions; request .html/.json chooses format. JSON templates
can use {{json .}}. Plain .html/.json files are not treated as templates.

```sh
bingo generate controller Reports
bingo generate model Task name:string completed:bool
bingo generate migration add_priority_to_tasks priority:integer
bingo db status
bingo db version
bingo db rollback
```

Controller generation creates ReportsIndex/ReportsShow functions and .ego views.
Register them explicitly in config/routes.go. Model generation creates a native
GORM struct and a create-table migration. Supported fields: string/text,
bool/boolean, integer/int, float, datetime. Unsupported migration patterns create
an SQL skeleton with a failing guard. Review SQL; never edit applied migrations.

Database configuration lives in config/database.go as a typed Go function:

```go
func Database(environment string) (bingo.DatabaseConfig, error)
```

main.go registers it with app.Database(config.Database). Server and commands use
that same function at runtime. The scaffold supports development/test/production
and reads BINGO_DEVELOPMENT_DATABASE, BINGO_TEST_DATABASE, or
BINGO_PRODUCTION_DATABASE with database/<environment>.sqlite3 defaults. Unknown
environments and empty paths are rejected. Paths are relative to the app directory.
No JSON/template configuration or external config override is used. Change logic
by editing config/database.go and rebuilding; deployment values come from runtime
environment variables. Startup never migrates. Use --env for database commands.

```sh
bingo build
./bin/app db migrate
./bin/app help
./bin/app
```

bin/app compiles config code and embeds views, SQL, and runtime commands. It needs neither
Go nor an installed Bingo CLI. Deploy the binary, run migrations from the data
directory, then start the server. BINGO_APP_DIR selects the data directory;
BINGO_ADDR selects the address.
BINGO_PRODUCTION_DATABASE overrides the production SQLite path in the default
config. New migrations require rebuilding. Production has no watcher or debug
error details and shuts down gracefully on SIGINT/SIGTERM. SQLite uses CGO;
building requires a C compiler for the target platform.

Custom handlers live in commands/. config/commands.go registers them directly:

```go
func RegisterCommands(registry *bingo.Commands) {
    registry.Register("todo_count", "Count todos", commands.TodoCount)
}
```

main.go calls app.Commands(config.RegisterCommands). Names are snake_case. CommandContext
provides Context, DB, Args, In, Out, Err, and Environment. Return errors, never
os.Exit. Development bingo todo_count runs the same handler as production
./bin/app todo_count. Help/version skip database initialization.

Development serve rebuilds when Go source/config changes and keeps the current
server on failed builds. Views are read from disk on every request. Flags precede
generator names: bingo generate model --app PATH Task name:string. The local Bingo
checkout is referenced in go.mod/go.work; update those paths when relocating it.

```sh
go test ./...
```

Framework validation:

```sh
go test -race ./...
go vet ./...
bingo db migrate --app examples/todo
bingo serve --app examples/todo
```

Integration tests exercise real production deployments and development rebuilds
through localhost. No editor plugin is implemented yet; .ego lets a future plugin
target Bingo templates while leaving ordinary JSON/HTML files untouched.

## Background jobs

`main.go` calls `app.Jobs(config.RegisterJobs)`. Register snake_case handlers and
five-field UTC recurring schedules explicitly in `config/jobs.go`:

```go
func RegisterJobs(registry *bingo.Jobs) {
    registry.Register("send_reminder", jobs.SendReminder)
    registry.Schedule("daily_reminder", "0 9 * * *", "send_reminder",
        jobs.ReminderInput{UserID: 42})
}
```

Handlers live in `jobs/` with signature `func(*bingo.JobContext) error`.
`c.Decode(&input)` decodes the JSON payload into your struct and rejects unknown
fields. `c.DB` is native GORM bound to `c.Context`; `c.ID`, `c.Attempt`, and `c.Key`
identify the execution. Store identifiers in payloads and fetch records inside
handlers. Never retain a request or its DB session for later work.

Enqueue from requests, commands, and jobs using the same API:

```go
id, err := c.Enqueue("send_reminder", jobs.ReminderInput{UserID: 42})
id, err = c.Enqueue("send_reminder", jobs.ReminderInput{UserID: 42}, bingo.JobOptions{
    RunAt: time.Now().Add(10 * time.Minute),
    Key: "reminder:user:42",
})
```

Omit `RunAt` for immediate work. Optional `Key` deduplicates by job name while
pending/running: concurrent enqueues return the existing ID. Completed and failed
jobs release keys. Delivery is at least once; handlers must be safe to retry.
Enqueue through a transaction-bound `c.DB` commits or rolls back with native GORM
application writes. Payloads are limited to 1 MiB.

Goqite provides SQLite delivery and leases. Bingo stores JSON payloads, status,
attempts, and recurring cursors in the same database. Apply the explicit Goose
job migration first. For an existing application, add the new migration with the
next unused version; never overwrite an applied migration.

```sh
bingo db migrate
bingo worker                       # development; default concurrency 1
bingo worker --concurrency 2
bingo build
./bin/app db migrate
./bin/app worker                   # production; separate from web process
```

The separate todo example registers `todo_count` and `daily_todo_count` at 09:00 UTC. Workers
support `--env development|test|production`, poll messages every 200 ms, and
poll recurring schedules every second. Web startup does not start a worker or
migrate. Supervise web and worker processes separately, using the same SQLite
file on the same host and the same release/configuration.

`JobOptions.MaxAttempts` defaults to 3 (allowed 1–100); `Timeout` defaults to five
minutes. Errors, panics, and timeouts retry with exponential backoff from one
second, capped at 64 seconds. Final failures retain their errors. Handlers must
honor `c.Context`: Go cannot forcibly stop a handler ignoring cancellation.
Shutdown cancels handlers and waits for them to return. Thirty-second leases
renew every ten seconds, allowing abandoned jobs to recover; receipt checks
prevent stale acknowledgements.

Recurring schedules record one occurrence per schedule/timestamp. Missed recurring
occurrences during downtime are skipped; already-enqueued delayed jobs survive
restart. Occurrences can overlap when concurrency permits. Keep schedule names
stable. `bingo_jobs` retains completed/failed records, `attempts`, `last_error`,
and timestamps for native SQL/GORM inspection. Automatic record pruning and a
failed-job replay command are not included in this first version. Job schema
is created only through reviewed Goose migrations, never at startup.

# __PROJECT_NAME__

A Bingo application with function handlers, explicit routes, native GORM, SQLite,
and Goose SQL migrations.

```sh
bingo db migrate
bingo serve
```

Open [the todo collection](http://localhost:8080/todos). HTML and JSON are available
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
./bin/app todo_count
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

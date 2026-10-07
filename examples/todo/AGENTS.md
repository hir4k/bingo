# Bingo application contract

Write code for human readers: meaningful variables, early returns, simple
composition, and comments explaining reasons. Read framework source before adding
framework calls; do not invent APIs.

- main.go is the only root Go source. It creates bingo.New(), supplies embedded
  assets through app.Views, registers config.Database/RegisterRoutes/RegisterCommands, and
  calls app.Run. No arguments starts the server; arguments dispatch commands.
- config/routes.go uses package config. Routers expose Get, Post, Put, Patch,
  Delete, Group, and Use. Routes accept path, handler, and an optional full name:
  root.Get("/todos/:id", controllers.TodosShow, "todos.show"). No Resource API,
  controller structs, constructors, reflection, or action-name strings.
- Handlers have signature func(*bingo.Context) error. Each request gets a fresh
  Context with Request, ResponseWriter, Params, Format, and native *gorm.DB bound
  to Request.Context(). Return errors for central handling; bingo.HTTPError
  provides deliberate HTTP status/messages. Never retain request DB for jobs.
- Groups only control prefixes/middleware. Declare Use before routes/groups in
  that scope. Names are explicit, never inferred or prefixed by groups. Duplicate
  method/path patterns and names fail at setup. Registration freezes at Handler.
- Named parameters are strings: c.Params["username"]. Use ParamInt for positive
  numeric IDs. Static paths take priority over parameters. .html/.json select
  format, with HTML default. Unregistered paths return 404; wrong methods 405.
- c.URL("todos.show", map[string]string{"id":"1"}) builds a named URL; collection
  routes need no parameter map. Parameters are escaped; missing parameters and
  unknown names return errors. Templates use {{url "todos.show" "id" .ID}}.
- Return c.Render("todos/index", data). View paths are explicit; no namespace
  inference. Files are views/todos/index.html.ego and index.json.ego. Go templates
  use html/template for HTML, text/template for JSON, and {{json .}} for JSON
  encoding. .ego is a naming convention, not Ruby or an editor plugin.
- models contains native GORM structs. SQLite is supported by default. Never use
  AutoMigrate or startup migrations. Goose alone applies reviewed SQL in
  database/migrations. Never edit applied migrations. Generate controllers as
  functions, then register routes explicitly.
- config/database.go defines Database(environment string) (bingo.DatabaseConfig,
  error), registered once through app.Database(config.Database). It runs at runtime
  for server and commands. Use os.LookupEnv for deployment values; unknown
  environments return errors. Bingo validates SQLite/nonempty paths and resolves
  relative paths against app.Directory. Do not add JSON/template config fallbacks.
- Production compiles configuration code and embeds only views and
  database/migrations. Configuration logic changes need a rebuild; runtime env
  values do not. Never capture deployment values at build time or embed Go files.
- bingo serve is development only and watches source/config; bingo build produces
  bin/app in production mode. Neither migrates. Use ./bin/app db migrate explicitly.
  Production defaults to production; development CLI db commands default to
  development. Migrations are embedded at build time; rebuild after adding SQL.
- config/commands.go defines RegisterCommands(*bingo.Commands) and registers
  handlers directly with registry.Register(name, description, commands.Handler).
  commands/ contains handlers only; never add a commands.Register wrapper. Names
  are lowercase snake_case; duplicates/reserved names fail. Handlers
  accept *bingo.CommandContext and return error. It supplies Context, native DB,
  Args, In, Out, Err, and Environment. Never use init side effects or os.Exit.
  Development bingo NAME delegates to the same handler as ./bin/app NAME.
- Run go test ./... and bingo build after changes. Add meaningful behavior tests.

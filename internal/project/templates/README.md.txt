# __PROJECT_NAME__

An empty Bingo application. Start the development server with `bingo serve`.
There are no registered routes, so requests return 404 until you add them.

The configuration files contain local examples, contracts, and setup commands:

- `config/routes.go`: handlers, views, routing, names, middleware, controller generator.
- `config/database.go`: SQLite, runtime environment variables, models, migrations.
- `config/commands.go`: custom command functions and explicit registration.
- `config/jobs.go`: payloads, enqueueing, retries, queue migration, recurring schedules.

`main.go` is the only root Go source. Add application code to `controllers/`,
`models/`, `commands/`, and `jobs/`, and templates to `views/`. Empty folders contain
`.keep` files so Git preserves them. Keep the views placeholder until real templates exist: `all:views` includes
`.keep` so the empty views folder compiles into production assets.

```sh
bingo generate controller Users
# Register the generated handlers in config/routes.go.
bingo generate model User username:string active:bool
# Review the generated SQL, then apply it explicitly.
bingo db migrate
bingo serve
```

The skeleton includes `database/migrations/000001_create_bingo_jobs.sql` for
queue infrastructure. Review it and run `bingo db migrate` before using jobs.
Create/register a handler as shown in `config/jobs.go`, then
start `bingo worker` in a separate terminal. No default jobs or commands are added.

```sh
bingo build
./bin/app db migrate
./bin/app help
./bin/app
```

Production `bin/app` embeds views and SQL migrations and compiles configuration
and handlers. It needs neither Go nor the development CLI. Runtime environment
variables still work without rebuilding. New configuration logic, handlers, or
migration files require rebuilding. Server and worker never migrate automatically.
Run `./bin/app worker` separately when background jobs are configured, using the
same SQLite file as the server. Database defaults are environment-specific paths
in `database/`; see config/database.go for deployment overrides.

Generated modules currently reference a local Bingo checkout through `go.mod` and
`go.work`. Update their paths when relocating the checkout. Run `go test ./...`
after changing application code. Ordinary `.html`/`.json` files are unaffected by
Bingo's `.html.ego`/`.json.ego` Go template naming convention.

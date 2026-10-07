package bingo

import (
	"bytes"
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"

	"github.com/robfig/cron/v3"
	"gorm.io/gorm"
	"maragu.dev/goqite"
)

type JobHandler func(*JobContext) error

type JobOptions struct {
	RunAt       time.Time
	Key         string
	MaxAttempts int
	Timeout     time.Duration
}

type Jobs struct {
	handlers  map[string]JobHandler
	schedules map[string]jobSchedule
	frozen    bool
}
type jobSchedule struct {
	expression, job string
	payload         []byte
	cron            cron.Schedule
}

func (j *Jobs) Register(name string, handler JobHandler) {
	if j.frozen {
		panic("bingo: jobs are frozen")
	}
	if !commandName.MatchString(name) || handler == nil {
		panic("bingo: jobs require a snake_case name and handler")
	}
	if j.handlers == nil {
		j.handlers = make(map[string]JobHandler)
	}
	if j.handlers[name] != nil {
		panic("bingo: duplicate job " + name)
	}
	j.handlers[name] = handler
}

// Schedule uses five-field cron expressions in UTC. Registration order is explicit:
// register the handler before its recurring schedules.
func (j *Jobs) Schedule(name, expression, job string, payload any) {
	if j.frozen {
		panic("bingo: jobs are frozen")
	}
	if !commandName.MatchString(name) || j.handlers[job] == nil {
		panic("bingo: schedule requires a snake_case name and registered job")
	}
	if len(strings.Fields(expression)) != 5 {
		panic("bingo: schedules require five cron fields in UTC")
	}
	parser := cron.NewParser(cron.Minute | cron.Hour | cron.Dom | cron.Month | cron.Dow)
	schedule, err := parser.Parse(expression)
	if err != nil || schedule.Next(time.Now().UTC()).IsZero() {
		panic("bingo: invalid cron schedule " + expression)
	}
	body, err := json.Marshal(payload)
	if err != nil || len(body) > 1024*1024 {
		panic("bingo: invalid schedule payload")
	}
	if j.schedules == nil {
		j.schedules = make(map[string]jobSchedule)
	}
	if _, exists := j.schedules[name]; exists {
		panic("bingo: duplicate schedule " + name)
	}
	j.schedules[name] = jobSchedule{expression, job, body, schedule}
}

func (a *App) Jobs(register func(*Jobs)) {
	if register == nil {
		panic("bingo: job registration cannot be nil")
	}
	register(a.jobs)
}

type JobContext struct {
	Context context.Context
	DB      *gorm.DB
	ID      string
	Attempt int
	Key     string
	payload []byte
	app     *App
}

func (c *JobContext) Decode(destination any) error {
	decoder := json.NewDecoder(bytes.NewReader(c.payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("decode job payload: %w", err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return fmt.Errorf("job payload must contain one JSON value")
	}
	return nil
}

func (c *Context) Enqueue(name string, payload any, options ...JobOptions) (string, error) {
	return c.app.enqueue(c.Request.Context(), c.DB, name, payload, options...)
}
func (c *CommandContext) Enqueue(name string, payload any, options ...JobOptions) (string, error) {
	return c.app.enqueue(c.Context, c.DB, name, payload, options...)
}
func (c *JobContext) Enqueue(name string, payload any, options ...JobOptions) (string, error) {
	return c.app.enqueue(c.Context, c.DB, name, payload, options...)
}

// Joining a native GORM transaction makes application writes and enqueue atomic.
// Outside a transaction, both the job record and delivery message commit together.
func jobTransaction(ctx context.Context, db *gorm.DB, work func(*sql.Tx) error) error {
	connection := db.Statement.ConnPool
	if prepared, ok := connection.(*gorm.PreparedStmtTX); ok {
		connection = prepared.Tx
	}
	if tx, ok := connection.(*sql.Tx); ok {
		return work(tx)
	}
	if _, active := connection.(gorm.TxCommitter); active {
		return fmt.Errorf("enqueue requires a native SQLite transaction")
	}
	pool, err := db.DB()
	if err != nil {
		return err
	}
	tx, err := pool.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if err := work(tx); err != nil {
		return err
	}
	return tx.Commit()
}
func jobQueue(db *sql.DB) *goqite.Queue {
	return goqite.New(goqite.NewOpts{DB: db, Name: "bingo_jobs", MaxReceive: 2147483647, Timeout: 30 * time.Second})
}
func (a *App) enqueue(ctx context.Context, db *gorm.DB, name string, payload any, options ...JobOptions) (string, error) {
	if db == nil {
		return "", fmt.Errorf("jobs require a database")
	}
	if a.jobs.handlers[name] == nil {
		return "", fmt.Errorf("unknown job %q", name)
	}
	if len(options) > 1 {
		return "", fmt.Errorf("enqueue accepts one JobOptions value")
	}
	option := JobOptions{}
	if len(options) == 1 {
		option = options[0]
	}
	if option.MaxAttempts == 0 {
		option.MaxAttempts = 3
	}
	if option.Timeout == 0 {
		option.Timeout = 5 * time.Minute
	}
	if option.MaxAttempts < 1 || option.MaxAttempts > 100 || option.Timeout < time.Millisecond {
		return "", fmt.Errorf("invalid job attempts or timeout")
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	if len(body) > 1024*1024 {
		return "", fmt.Errorf("job payload exceeds 1 MiB")
	}
	pool, err := db.DB()
	if err != nil {
		return "", err
	}
	var id string
	err = jobTransaction(ctx, db, func(tx *sql.Tx) error {
		var insertError error
		id, insertError = a.insertJob(ctx, tx, jobQueue(pool), name, body, option, "", 0)
		return insertError
	})
	return id, err
}
func (a *App) insertJob(ctx context.Context, tx *sql.Tx, queue *goqite.Queue, name string, body []byte, option JobOptions, schedule string, occurrence int64) (string, error) {
	id := "job_" + rand.Text()
	now := time.Now().UnixMilli()
	result, err := tx.ExecContext(ctx, `INSERT INTO bingo_jobs(id,name,payload,dedupe_key,status,attempts,max_attempts,timeout_ms,created_at,updated_at,schedule_name,occurrence_at) VALUES(?,?,?,NULLIF(?,''),'pending',0,?,?,?,?,NULLIF(?,''),NULLIF(?,0)) ON CONFLICT DO NOTHING`, id, name, string(body), option.Key, option.MaxAttempts, option.Timeout.Milliseconds(), now, now, schedule, occurrence)
	if err != nil {
		return "", fmt.Errorf("enqueue job (apply database migrations first): %w", err)
	}
	count, err := result.RowsAffected()
	if err != nil {
		return "", err
	}
	if count == 0 {
		if schedule != "" {
			err = tx.QueryRowContext(ctx, `SELECT id FROM bingo_jobs WHERE schedule_name=? AND occurrence_at=?`, schedule, occurrence).Scan(&id)
		} else {
			err = tx.QueryRowContext(ctx, `SELECT id FROM bingo_jobs WHERE name=? AND dedupe_key=? AND status IN ('pending','running')`, name, option.Key).Scan(&id)
		}
		return id, err
	}
	delay := time.Until(option.RunAt)
	if delay < 0 {
		delay = 0
	}
	message, err := queue.SendAndGetIDTx(ctx, tx, goqite.Message{Body: []byte(id), Delay: delay})
	if err != nil {
		return "", err
	}
	_, err = tx.ExecContext(ctx, `UPDATE bingo_jobs SET message_id=? WHERE id=?`, string(message), id)
	return id, err
}

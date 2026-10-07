package bingo

import (
	"context"
	"database/sql"
	"errors"
	"flag"
	"fmt"
	"io"
	"sync"
	"time"

	"gorm.io/gorm"
	"maragu.dev/goqite"
)

type claimedJob struct {
	id, name, key                  string
	payload                        []byte
	attempts, maxAttempts, receipt int
	timeout                        time.Duration
	message                        goqite.ID
}

func (a *App) workerCommand(ctx context.Context, args []string, output io.Writer) error {
	flags := flag.NewFlagSet("worker", flag.ContinueOnError)
	flags.SetOutput(output)
	environment := flags.String("env", a.environment(), "database environment")
	concurrency := flags.Int("concurrency", 1, "number of simultaneous jobs (1-64)")
	if err := flags.Parse(args); err != nil {
		if err == flag.ErrHelp {
			return nil
		}
		return err
	}
	if flags.NArg() != 0 || *concurrency < 1 || *concurrency > 64 {
		return fmt.Errorf("worker expects --concurrency between 1 and 64")
	}
	config, err := a.DatabaseSettings(*environment)
	if err != nil {
		return err
	}
	db, err := OpenDatabase(config)
	if err != nil {
		return err
	}
	pool, err := db.DB()
	if err != nil {
		return err
	}
	defer pool.Close()
	fmt.Fprintf(output, "Bingo worker (%s), concurrency %d, schedules UTC\n", *environment, *concurrency)
	return a.runWorker(ctx, db, *concurrency)
}

func (a *App) runWorker(ctx context.Context, db *gorm.DB, concurrency int) error {
	pool, err := db.DB()
	if err != nil {
		return err
	}
	// Fail before launching goroutines; startup never creates or migrates tables.
	for _, table := range []string{"bingo_jobs", "bingo_schedules", "goqite"} {
		rows, err := pool.QueryContext(ctx, "SELECT 1 FROM "+table+" LIMIT 0")
		if err != nil {
			return fmt.Errorf("worker requires job migrations; run db migrate: %w", err)
		}
		rows.Close()
	}
	if err := a.prepareSchedules(ctx, db); err != nil {
		return err
	}
	workerContext, cancel := context.WithCancel(ctx)
	defer cancel()
	failures := make(chan error, concurrency+1)
	var workers sync.WaitGroup
	workers.Add(concurrency + 1)
	go func() { defer workers.Done(); failures <- a.runScheduler(workerContext, db) }()
	for index := 0; index < concurrency; index++ {
		go func() { defer workers.Done(); failures <- a.consumeJobs(workerContext, db, jobQueue(pool)) }()
	}
	err = <-failures
	cancel()
	workers.Wait()
	if errors.Is(err, context.Canceled) && ctx.Err() != nil {
		return nil
	}
	return err
}

func (a *App) consumeJobs(ctx context.Context, db *gorm.DB, queue *goqite.Queue) error {
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		job, err := a.claimJob(ctx, db, queue)
		if err != nil {
			return err
		}
		if job == nil {
			if err := waitForJob(ctx, 200*time.Millisecond); err != nil {
				return err
			}
			continue
		}
		if err := a.performJob(ctx, db, queue, job); err != nil {
			return err
		}
	}
}
func waitForJob(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func (a *App) claimJob(ctx context.Context, db *gorm.DB, queue *goqite.Queue) (*claimedJob, error) {
	var job *claimedJob
	err := jobTransaction(ctx, db, func(tx *sql.Tx) error {
		message, err := queue.ReceiveTx(ctx, tx)
		if err != nil || message == nil {
			return err
		}
		item := &claimedJob{message: message.ID}
		var timeout int64
		err = tx.QueryRowContext(ctx, `SELECT id,name,payload,COALESCE(dedupe_key,''),attempts,max_attempts,timeout_ms FROM bingo_jobs WHERE id=?`, string(message.Body)).Scan(&item.id, &item.name, &item.payload, &item.key, &item.attempts, &item.maxAttempts, &timeout)
		if errors.Is(err, sql.ErrNoRows) {
			return queue.DeleteTx(ctx, tx, message.ID)
		}
		if err != nil {
			return err
		}
		if err = tx.QueryRowContext(ctx, `SELECT received FROM goqite WHERE id=?`, string(message.ID)).Scan(&item.receipt); err != nil {
			return err
		}
		item.timeout = time.Duration(timeout) * time.Millisecond
		if item.attempts >= item.maxAttempts || a.jobs.handlers[item.name] == nil {
			_, err = tx.ExecContext(ctx, `UPDATE bingo_jobs SET status='failed',last_error=?,finished_at=?,updated_at=? WHERE id=?`, "attempt limit reached or job handler unregistered", time.Now().UnixMilli(), time.Now().UnixMilli(), item.id)
			if err != nil {
				return err
			}
			return queue.DeleteTx(ctx, tx, message.ID)
		}
		item.attempts++
		_, err = tx.ExecContext(ctx, `UPDATE bingo_jobs SET status='running',attempts=?,updated_at=? WHERE id=?`, item.attempts, time.Now().UnixMilli(), item.id)
		if err != nil {
			return err
		}
		job = item
		return nil
	})
	return job, err
}

var errJobLeaseLost = errors.New("job lease lost")

// Every renewal and completion checks the receipt inside the write transaction.
// An old worker cannot acknowledge a message reclaimed after its lease expired.
func withJobLease(ctx context.Context, db *gorm.DB, job *claimedJob, work func(*sql.Tx) error) error {
	return jobTransaction(ctx, db, func(tx *sql.Tx) error {
		var receipt int
		err := tx.QueryRowContext(ctx, `SELECT received FROM goqite WHERE id=?`, string(job.message)).Scan(&receipt)
		if errors.Is(err, sql.ErrNoRows) || (err == nil && receipt != job.receipt) {
			return errJobLeaseLost
		}
		if err != nil {
			return err
		}
		return work(tx)
	})
}
func (a *App) performJob(ctx context.Context, db *gorm.DB, queue *goqite.Queue, job *claimedJob) error {
	jobContext, cancel := context.WithTimeout(ctx, job.timeout)
	defer cancel()
	heartbeatContext, stopHeartbeat := context.WithCancel(jobContext)
	heartbeatDone := make(chan error, 1)
	go func() {
		ticker := time.NewTicker(10 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-heartbeatContext.Done():
				heartbeatDone <- nil
				return
			case <-ticker.C:
				err := withJobLease(heartbeatContext, db, job, func(tx *sql.Tx) error { return queue.ExtendTx(heartbeatContext, tx, job.message, 30*time.Second) })
				if err != nil {
					cancel()
					heartbeatDone <- err
					return
				}
			}
		}
	}()
	execution := &JobContext{Context: jobContext, DB: db.WithContext(jobContext), ID: job.id, Attempt: job.attempts, Key: job.key, payload: job.payload, app: a}
	jobError := callJob(a.jobs.handlers[job.name], execution)
	if jobError == nil {
		jobError = jobContext.Err()
	}
	stopHeartbeat()
	leaseError := <-heartbeatDone
	if errors.Is(leaseError, errJobLeaseLost) {
		return nil
	}
	if leaseError != nil {
		return leaseError
	}
	// A signal cancels handler work, but acknowledgement still needs a short window.
	finishContext, finishCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer finishCancel()
	err := a.finishJob(finishContext, db, queue, job, jobError, ctx.Err() != nil)
	if errors.Is(err, errJobLeaseLost) {
		return nil
	}
	return err
}
func callJob(handler JobHandler, ctx *JobContext) (err error) {
	defer func() {
		if value := recover(); value != nil {
			err = fmt.Errorf("job panic: %v", value)
		}
	}()
	return handler(ctx)
}
func (a *App) finishJob(ctx context.Context, db *gorm.DB, queue *goqite.Queue, job *claimedJob, jobError error, interrupted bool) error {
	return withJobLease(ctx, db, job, func(tx *sql.Tx) error {
		status := "completed"
		message := ""
		retry := false
		if jobError != nil {
			message = jobError.Error()
			if len(message) > 4096 {
				message = message[:4096]
			}
			status = "failed"
			retry = job.attempts < job.maxAttempts
			if interrupted {
				retry = true
			}
			if retry {
				status = "pending"
			}
		}
		var finished any = time.Now().UnixMilli()
		if retry {
			finished = nil
		}
		_, err := tx.ExecContext(ctx, `UPDATE bingo_jobs SET status=?,last_error=?,finished_at=?,updated_at=? WHERE id=?`, status, message, finished, time.Now().UnixMilli(), job.id)
		if err != nil {
			return err
		}
		if retry {
			delay := time.Second << min(job.attempts-1, 6)
			if interrupted {
				delay = 0
			}
			return queue.ExtendTx(ctx, tx, job.message, delay)
		}
		return queue.DeleteTx(ctx, tx, job.message)
	})
}

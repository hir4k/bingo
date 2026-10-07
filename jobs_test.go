package bingo

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"gorm.io/gorm"
)

func jobTestApp(t *testing.T) (*App, *gorm.DB) {
	t.Helper()
	app := New()
	config := DatabaseConfig{Driver: "sqlite", Database: filepath.Join(t.TempDir(), "jobs.sqlite3")}
	if err := runMigrations(context.Background(), config, os.DirFS("examples/todo/database/migrations"), "migrate", os.Stderr); err != nil {
		t.Fatal(err)
	}
	db, err := OpenDatabase(config)
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := db.DB()
	t.Cleanup(func() { pool.Close() })
	return app, db
}
func TestJobDeduplicationAndTransactionRollback(t *testing.T) {
	app, db := jobTestApp(t)
	app.Jobs(func(j *Jobs) { j.Register("send_email", func(*JobContext) error { return nil }) })
	var wait sync.WaitGroup
	ids := make(chan string, 12)
	for i := 0; i < 12; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			id, err := app.enqueue(context.Background(), db, "send_email", map[string]int{"user": 42}, JobOptions{Key: "user:42"})
			if err != nil {
				t.Error(err)
			}
			ids <- id
		}()
	}
	wait.Wait()
	close(ids)
	var first string
	for id := range ids {
		if first == "" {
			first = id
		}
		if id != first {
			t.Fatalf("duplicate IDs: %s %s", first, id)
		}
	}
	var count int64
	if err := db.Table("goqite").Count(&count).Error; err != nil || count != 1 {
		t.Fatalf("messages=%d error=%v", count, err)
	}
	rollback := errors.New("rollback application write")
	err := db.Transaction(func(tx *gorm.DB) error {
		if _, err := app.enqueue(context.Background(), tx, "send_email", nil, JobOptions{Key: "rolled_back"}); err != nil {
			return err
		}
		return rollback
	})
	if !errors.Is(err, rollback) {
		t.Fatal(err)
	}
	if err := db.Table("bingo_jobs").Where("dedupe_key = ?", "rolled_back").Count(&count).Error; err != nil || count != 0 {
		t.Fatalf("rolled-back jobs=%d error=%v", count, err)
	}
}
func TestJobDelayRetryFailureAndKeyRelease(t *testing.T) {
	app, db := jobTestApp(t)
	app.Jobs(func(j *Jobs) {
		j.Register("fail_job", func(c *JobContext) error {
			var input struct{ Value int }
			if err := c.Decode(&input); err != nil {
				t.Fatal(err)
			}
			if input.Value != 42 {
				t.Fatal(input)
			}
			return errors.New("service unavailable")
		})
	})
	ctx := context.Background()
	id, err := app.enqueue(ctx, db, "fail_job", map[string]int{"Value": 42}, JobOptions{RunAt: time.Now().Add(time.Hour), Key: "one", MaxAttempts: 2})
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := db.DB()
	queue := jobQueue(pool)
	job, err := app.claimJob(ctx, db, queue)
	if err != nil || job != nil {
		t.Fatalf("delayed job claimed: %v %v", job, err)
	}
	if err := db.Exec("UPDATE goqite SET timeout='2000-01-01T00:00:00.000Z'").Error; err != nil {
		t.Fatal(err)
	}
	job, err = app.claimJob(ctx, db, queue)
	if err != nil || job == nil {
		t.Fatalf("claim: %v", err)
	}
	if err := app.performJob(ctx, db, queue, job); err != nil {
		t.Fatal(err)
	}
	var status string
	db.Raw("SELECT status FROM bingo_jobs WHERE id=?", id).Scan(&status)
	if status != "pending" {
		t.Fatal(status)
	}
	db.Exec("UPDATE goqite SET timeout='2000-01-01T00:00:00.000Z'")
	job, err = app.claimJob(ctx, db, queue)
	if err != nil || job == nil {
		t.Fatal(err)
	}
	if err := app.performJob(ctx, db, queue, job); err != nil {
		t.Fatal(err)
	}
	db.Raw("SELECT status FROM bingo_jobs WHERE id=?", id).Scan(&status)
	if status != "failed" {
		t.Fatal(status)
	}
	replacement, err := app.enqueue(ctx, db, "fail_job", nil, JobOptions{Key: "one"})
	if err != nil || replacement == id {
		t.Fatalf("key not released: %s %v", replacement, err)
	}
}
func TestJobLeaseRejectsStaleAcknowledgement(t *testing.T) {
	app, db := jobTestApp(t)
	app.Jobs(func(j *Jobs) { j.Register("do_work", func(*JobContext) error { return nil }) })
	ctx := context.Background()
	_, err := app.enqueue(ctx, db, "do_work", nil)
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := db.DB()
	queue := jobQueue(pool)
	first, err := app.claimJob(ctx, db, queue)
	if err != nil {
		t.Fatal(err)
	}
	db.Exec("UPDATE goqite SET timeout='2000-01-01T00:00:00.000Z'")
	second, err := app.claimJob(ctx, db, queue)
	if err != nil {
		t.Fatal(err)
	}
	if err := app.finishJob(ctx, db, queue, first, nil, false); !errors.Is(err, errJobLeaseLost) {
		t.Fatalf("stale completion: %v", err)
	}
	if err := app.finishJob(ctx, db, queue, second, nil, false); err != nil {
		t.Fatal(err)
	}
}
func TestRecurringJobOccurrenceIsUnique(t *testing.T) {
	app, db := jobTestApp(t)
	app.Jobs(func(j *Jobs) {
		j.Register("do_work", func(*JobContext) error { return nil })
		j.Schedule("daily_work", "0 9 * * *", "do_work", nil)
	})
	ctx := context.Background()
	if err := app.prepareSchedules(ctx, db); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	if err := db.Exec("UPDATE bingo_schedules SET next_run=?", now.Add(-time.Second).UnixMilli()).Error; err != nil {
		t.Fatal(err)
	}
	var wait sync.WaitGroup
	for i := 0; i < 5; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			if err := app.enqueueSchedules(ctx, db, now); err != nil {
				t.Error(err)
			}
		}()
	}
	wait.Wait()
	var count int64
	db.Table("bingo_jobs").Count(&count)
	if count != 1 {
		t.Fatalf("scheduled jobs=%d", count)
	}
}
func TestWorkerCancellationAndMissingMigration(t *testing.T) {
	app, db := jobTestApp(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := app.runWorker(ctx, db, 1); !errors.Is(err, context.Canceled) {
		t.Fatalf("canceled startup: %v", err)
	}
	if err := db.Exec("DROP TABLE bingo_jobs").Error; err != nil {
		t.Fatal(err)
	}
	if err := app.runWorker(context.Background(), db, 1); err == nil {
		t.Fatal("worker started without schema")
	}
}

func TestWorkerRunsJobAndStopsOnCancellation(t *testing.T) {
	app, db := jobTestApp(t)
	ran := make(chan int, 1)
	app.Jobs(func(j *Jobs) {
		j.Register("do_work", func(c *JobContext) error {
			var input struct{ Value int }
			if err := c.Decode(&input); err != nil {
				return err
			}
			ran <- input.Value
			return nil
		})
	})
	id, err := app.enqueue(context.Background(), db, "do_work", map[string]int{"Value": 42})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- app.runWorker(ctx, db, 2) }()
	select {
	case value := <-ran:
		if value != 42 {
			t.Fatal(value)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("worker did not execute job")
	}
	// Allow the successful handler's acknowledgement to commit before shutdown.
	deadline := time.Now().Add(5 * time.Second)
	for {
		var status string
		if err := db.Raw("SELECT status FROM bingo_jobs WHERE id=?", id).Scan(&status).Error; err != nil {
			t.Fatal(err)
		}
		if status == "completed" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("job did not complete")
		}
		time.Sleep(10 * time.Millisecond)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("worker did not stop")
	}
}

func TestDeduplicationAcrossDatabaseConnections(t *testing.T) {
	app, db := jobTestApp(t)
	app.Jobs(func(j *Jobs) { j.Register("do_work", func(*JobContext) error { return nil }) })
	var database string
	db.Raw("SELECT file FROM pragma_database_list WHERE name='main'").Scan(&database)
	second, err := OpenDatabase(DatabaseConfig{Driver: "sqlite", Database: database})
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := second.DB()
	defer pool.Close()
	var wait sync.WaitGroup
	ids := make(chan string, 10)
	for i := 0; i < 10; i++ {
		connection := db
		if i%2 == 0 {
			connection = second
		}
		wait.Add(1)
		go func(connection *gorm.DB) {
			defer wait.Done()
			id, err := app.enqueue(context.Background(), connection, "do_work", nil, JobOptions{Key: "same"})
			if err != nil {
				t.Error(err)
			}
			ids <- id
		}(connection)
	}
	wait.Wait()
	close(ids)
	var first string
	for id := range ids {
		if first == "" {
			first = id
		}
		if id != first {
			t.Fatalf("cross-connection duplicate: %s %s", first, id)
		}
	}
}

func TestJobValidationAndPanicFailure(t *testing.T) {
	app, db := jobTestApp(t)
	app.Jobs(func(j *Jobs) { j.Register("panic_job", func(*JobContext) error { panic("unexpected failure") }) })
	ctx := context.Background()
	if _, err := app.enqueue(ctx, db, "missing", nil); err == nil {
		t.Fatal("unknown job accepted")
	}
	if _, err := app.enqueue(ctx, db, "panic_job", nil, JobOptions{MaxAttempts: -1}); err == nil {
		t.Fatal("invalid attempts accepted")
	}
	if err := (&JobContext{payload: []byte(`{"unexpected":true}`)}).Decode(&struct{}{}); err == nil {
		t.Fatal("unknown payload field accepted")
	}
	id, err := app.enqueue(ctx, db, "panic_job", nil, JobOptions{MaxAttempts: 1})
	if err != nil {
		t.Fatal(err)
	}
	pool, _ := db.DB()
	queue := jobQueue(pool)
	job, err := app.claimJob(ctx, db, queue)
	if err != nil {
		t.Fatal(err)
	}
	if err := app.performJob(ctx, db, queue, job); err != nil {
		t.Fatal(err)
	}
	var record struct {
		Status    string
		LastError string
	}
	if err := db.Table("bingo_jobs").Where("id=?", id).Take(&record).Error; err != nil {
		t.Fatal(err)
	}
	if record.Status != "failed" || record.LastError != "job panic: unexpected failure" {
		t.Fatal(record)
	}
}

func TestEnqueueJoinsPreparedGORMTransaction(t *testing.T) {
	app, db := jobTestApp(t)
	app.Jobs(func(j *Jobs) { j.Register("do_work", func(*JobContext) error { return nil }) })
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rollback := errors.New("rollback prepared transaction")
	err := db.WithContext(ctx).Session(&gorm.Session{PrepareStmt: true}).Transaction(func(tx *gorm.DB) error {
		if _, err := app.enqueue(ctx, tx, "do_work", nil); err != nil {
			return err
		}
		return rollback
	})
	if !errors.Is(err, rollback) {
		t.Fatal(err)
	}
	var count int64
	if err := db.Table("bingo_jobs").Count(&count).Error; err != nil || count != 0 {
		t.Fatalf("prepared transaction jobs=%d error=%v", count, err)
	}
}

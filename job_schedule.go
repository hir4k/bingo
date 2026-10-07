package bingo

import (
	"context"
	"database/sql"
	"gorm.io/gorm"
	"time"
)

// Starting a worker advances overdue cron cursors. Missed recurring occurrences
// are skipped; already-enqueued immediate and delayed jobs remain durable.
func (a *App) prepareSchedules(ctx context.Context, db *gorm.DB) error {
	if len(a.jobs.schedules) == 0 {
		return ctx.Err()
	}
	return jobTransaction(ctx, db, func(tx *sql.Tx) error {
		now := time.Now().UTC()
		for name, schedule := range a.jobs.schedules {
			next := schedule.cron.Next(now).UnixMilli()
			_, err := tx.ExecContext(ctx, `INSERT INTO bingo_schedules(name,expression,job,payload,next_run) VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET expression=excluded.expression,job=excluded.job,payload=excluded.payload,next_run=CASE WHEN bingo_schedules.expression!=excluded.expression OR bingo_schedules.job!=excluded.job OR bingo_schedules.payload!=excluded.payload OR bingo_schedules.next_run<? THEN excluded.next_run ELSE bingo_schedules.next_run END`, name, schedule.expression, schedule.job, string(schedule.payload), next, now.UnixMilli())
			if err != nil {
				return err
			}
		}
		return nil
	})
}
func (a *App) runScheduler(ctx context.Context, db *gorm.DB) error {
	for {
		if err := a.enqueueSchedules(ctx, db, time.Now().UTC()); err != nil {
			return err
		}
		if err := waitForJob(ctx, time.Second); err != nil {
			return err
		}
	}
}
func (a *App) enqueueSchedules(ctx context.Context, db *gorm.DB, now time.Time) error {
	pool, err := db.DB()
	if err != nil {
		return err
	}
	if len(a.jobs.schedules) == 0 {
		return ctx.Err()
	}
	return jobTransaction(ctx, db, func(tx *sql.Tx) error {
		for name, schedule := range a.jobs.schedules {
			var occurrence int64
			if err := tx.QueryRowContext(ctx, `SELECT next_run FROM bingo_schedules WHERE name=?`, name).Scan(&occurrence); err != nil {
				return err
			}
			if occurrence > now.UnixMilli() {
				continue
			}
			options := JobOptions{MaxAttempts: 3, Timeout: 5 * time.Minute}
			if _, err := a.insertJob(ctx, tx, jobQueue(pool), schedule.job, schedule.payload, options, name, occurrence); err != nil {
				return err
			}
			if _, err := tx.ExecContext(ctx, `UPDATE bingo_schedules SET next_run=? WHERE name=?`, schedule.cron.Next(now).UnixMilli(), name); err != nil {
				return err
			}
		}
		return nil
	})
}

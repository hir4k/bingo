from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import mapped_column


def Integer(*, primary_key: bool = False, default=None, nullable: bool = False):
    return mapped_column(
        sa.Integer,
        primary_key=primary_key,
        default=default,
        nullable=nullable and not primary_key,
    )


def String(*, max_length: int = 255, default=None, nullable: bool = False):
    return mapped_column(sa.String(max_length), default=default, nullable=nullable)


def Text(*, default=None, nullable: bool = False):
    return mapped_column(sa.Text, default=default, nullable=nullable)


def Boolean(*, default=False, nullable: bool = False):
    return mapped_column(sa.Boolean, default=default, nullable=nullable)


def Date(*, default=None, nullable: bool = False):
    return mapped_column(sa.Date, default=default, nullable=nullable)


def DateTime(
    *,
    default=None,
    nullable: bool = False,
    auto_now_add: bool = False,
    auto_now: bool = False,
):
    def current_time():
        return datetime.now(UTC)

    column_default = current_time if auto_now_add or auto_now else default
    onupdate = current_time if auto_now else None
    return mapped_column(
        sa.DateTime(timezone=True),
        default=column_default,
        onupdate=onupdate,
        nullable=nullable,
    )


def Float(*, default=None, nullable: bool = False):
    return mapped_column(sa.Float, default=default, nullable=nullable)


def Decimal(
    *,
    precision: int = 10,
    scale: int = 2,
    default=None,
    nullable: bool = False,
):
    return mapped_column(
        sa.Numeric(precision, scale), default=default, nullable=nullable
    )

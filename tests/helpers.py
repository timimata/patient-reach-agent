"""Shared test vocabulary: a fixed week to live in."""

from datetime import datetime


def mon(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 21, hour, minute)  # a Monday


def tue(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 22, hour, minute)


def wed(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 23, hour, minute)


def thu(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 24, hour, minute)


def fri(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 25, hour, minute)

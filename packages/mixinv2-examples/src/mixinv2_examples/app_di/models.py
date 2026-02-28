"""Shared data models for the app_di fixture package."""

from dataclasses import dataclass


@dataclass
class User:
    user_id: int
    name: str

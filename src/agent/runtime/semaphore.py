from __future__ import annotations

import asyncio
from enum import Enum


class SemaphoreState(str, Enum):
    idle = "idle"
    user_typing = "user_typing"
    llm_running = "llm_running"
    task_running = "task_running"


class ExecutionSemaphore:
    """
    Single asyncio lock shared by the CLI, scheduler, and runtime.

    The lock is held continuously from the moment the CLI shows the input
    prompt (user_typing) through the entire LLM reply (llm_running).
    Background tasks (task_running) also hold the lock, so the CLI cannot
    show a new prompt while a task is executing.

    The HTTP server never touches this semaphore.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state = SemaphoreState.idle
        self._pre_task_state = SemaphoreState.idle

    @property
    def state(self) -> SemaphoreState:
        return self._state

    @property
    def is_idle(self) -> bool:
        return self._state == SemaphoreState.idle

    async def acquire_typing(self) -> None:
        """Wait for any running task/LLM to finish, then mark as typing.
        State is set INSIDE the lock to avoid a race with acquire_task()."""
        async with self._lock:
            self._state = SemaphoreState.user_typing
        # lock released — scheduler may now grab it, will see user_typing as pre_task_state

    async def transition_to_llm(self) -> None:
        """Called on Enter — acquires the lock and moves to llm_running."""
        assert self._state == SemaphoreState.user_typing, (
            f"transition_to_llm() called in state {self._state}"
        )
        await self._lock.acquire()
        self._state = SemaphoreState.llm_running

    async def acquire_task(self) -> None:
        """Acquire the lock for background task execution."""
        self._pre_task_state = self._state
        await self._lock.acquire()
        self._state = SemaphoreState.task_running

    def mark_typing(self) -> None:
        """Called when user starts typing — blocks new tasks without acquiring lock."""
        if self._state == SemaphoreState.idle:
            self._state = SemaphoreState.user_typing

    def mark_idle(self) -> None:
        """Called when user clears input — allow tasks again."""
        if self._state == SemaphoreState.user_typing:
            self._state = SemaphoreState.idle

    @property
    def is_available_for_tasks(self) -> bool:
        """True only when idle — user_typing blocks new tasks."""
        return self._state == SemaphoreState.idle

    def release(self) -> None:
        """Release the lock — restores pre-task state or returns to idle."""
        if self._state == SemaphoreState.task_running:
            self._state = self._pre_task_state
            self._pre_task_state = SemaphoreState.idle
        else:
            self._state = SemaphoreState.idle
        self._lock.release()

import pytest

from agent.state import MemoryStateStore


@pytest.fixture
def store() -> MemoryStateStore:
    return MemoryStateStore()


@pytest.mark.asyncio
async def test_create_returns_new_state(store: MemoryStateStore) -> None:
    state = await store.create()
    assert state.session_id
    assert state.messages == []
    assert state.collected_fields == {}


@pytest.mark.asyncio
async def test_create_with_custom_id(store: MemoryStateStore) -> None:
    state = await store.create(session_id="custom-123")
    assert state.session_id == "custom-123"


@pytest.mark.asyncio
async def test_get_returns_stored_state(store: MemoryStateStore) -> None:
    created = await store.create()
    fetched = await store.get(created.session_id)
    assert fetched.session_id == created.session_id


@pytest.mark.asyncio
async def test_get_nonexistent_raises_key_error(store: MemoryStateStore) -> None:
    with pytest.raises(KeyError):
        await store.get("nonexistent")


@pytest.mark.asyncio
async def test_save_updates_existing(store: MemoryStateStore) -> None:
    state = await store.create()
    state.add_message("user", "hello")
    await store.save(state)

    fetched = await store.get(state.session_id)
    assert len(fetched.messages) == 1
    assert fetched.messages[0].content == "hello"


@pytest.mark.asyncio
async def test_delete_removes_state(store: MemoryStateStore) -> None:
    state = await store.create()
    await store.delete(state.session_id)
    with pytest.raises(KeyError):
        await store.get(state.session_id)


@pytest.mark.asyncio
async def test_delete_nonexistent_raises_key_error(store: MemoryStateStore) -> None:
    with pytest.raises(KeyError):
        await store.delete("nonexistent")


@pytest.mark.asyncio
async def test_create_duplicate_raises_value_error(store: MemoryStateStore) -> None:
    await store.create(session_id="dup-id")
    with pytest.raises(ValueError):
        await store.create(session_id="dup-id")


@pytest.mark.asyncio
async def test_get_returns_deep_copy(store: MemoryStateStore) -> None:
    state = await store.create()
    await store.save(state)

    fetched = await store.get(state.session_id)
    fetched.add_message("user", "mutated")

    # The stored state should NOT be affected
    fetched_again = await store.get(state.session_id)
    assert len(fetched_again.messages) == 0

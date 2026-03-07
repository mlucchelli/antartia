from __future__ import annotations

import pytest

from agent.state.file_store import FileStateStore


@pytest.fixture
def store(tmp_path) -> FileStateStore:
    return FileStateStore(tmp_path)


@pytest.mark.asyncio
async def test_create_writes_file(store: FileStateStore, tmp_path) -> None:
    state = await store.create()
    path = tmp_path / f"{state.session_id}.json"
    assert path.exists()


@pytest.mark.asyncio
async def test_create_with_custom_id(store: FileStateStore, tmp_path) -> None:
    state = await store.create("my-session")
    assert state.session_id == "my-session"
    assert (tmp_path / "my-session.json").exists()


@pytest.mark.asyncio
async def test_get_reads_back(store: FileStateStore) -> None:
    state = await store.create("s1")
    state.add_message("user", "hello")
    await store.save(state)

    loaded = await store.get("s1")
    assert loaded.session_id == "s1"
    assert len(loaded.messages) == 1
    assert loaded.messages[0].content == "hello"


@pytest.mark.asyncio
async def test_save_updates_file(store: FileStateStore) -> None:
    state = await store.create("s1")
    state.collect_field("name", "Alice", 0.9)
    await store.save(state)

    loaded = await store.get("s1")
    assert "name" in loaded.collected_fields
    assert loaded.collected_fields["name"].value == "Alice"


@pytest.mark.asyncio
async def test_delete_removes_file(store: FileStateStore, tmp_path) -> None:
    await store.create("s1")
    await store.delete("s1")
    assert not (tmp_path / "s1.json").exists()


@pytest.mark.asyncio
async def test_get_nonexistent_raises(store: FileStateStore) -> None:
    with pytest.raises(KeyError):
        await store.get("nope")


@pytest.mark.asyncio
async def test_delete_nonexistent_raises(store: FileStateStore) -> None:
    with pytest.raises(KeyError):
        await store.delete("nope")


@pytest.mark.asyncio
async def test_create_duplicate_raises(store: FileStateStore) -> None:
    await store.create("s1")
    with pytest.raises(ValueError):
        await store.create("s1")

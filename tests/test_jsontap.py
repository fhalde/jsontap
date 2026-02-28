from __future__ import annotations

import asyncio

from jsontap import AsyncJsonNode, AsyncJsonFeed, jsontap

pytest = __import__("pytest")


async def _ingest_text(
    text: str, *, chunk_size: int = 1, per_chunk_yield: bool = True
) -> AsyncJsonNode:
    root = AsyncJsonNode()
    ingestor = AsyncJsonFeed(root)
    for i in range(0, len(text), chunk_size):
        ingestor.feed(text[i : i + chunk_size])
        if per_chunk_yield:
            await asyncio.sleep(0)
    ingestor.finish()
    return root


def _setup(text: str, *, chunk_size: int = 1):
    root = AsyncJsonNode()
    ingestor = AsyncJsonFeed(root)

    async def ingest():
        for i in range(0, len(text), chunk_size):
            ingestor.feed(text[i : i + chunk_size])
            await asyncio.sleep(0)
        ingestor.finish()

    return root, ingest


async def _run_live(text: str, consumer, *, chunk_size: int = 1):
    root = AsyncJsonNode()
    ingestor = AsyncJsonFeed(root)

    async def ingest():
        for i in range(0, len(text), chunk_size):
            ingestor.feed(text[i : i + chunk_size])
            await asyncio.sleep(0)
        ingestor.finish()

    return await asyncio.gather(consumer(root), ingest())


class TestReactiveExp:
    async def test_basic_object_and_stream(self):
        text = '{"user":{"name":"Alice"},"logs":["a","b","c"]}'

        async def consumer(root):
            user = await root["user"]
            logs = []
            async for item in root["logs"]:
                logs.append(await item)
            return user, logs

        (user, logs), _ = await _run_live(text, consumer)
        assert user == {"name": "Alice"}
        assert logs == ["a", "b", "c"]

    async def test_repeat_iteration_on_same_array(self):
        text = '{"logs":[1,2,3]}'

        async def consumer(root):
            first = []
            second = []
            async for item in root["logs"]:
                first.append(await item)
            async for item in root["logs"]:
                second.append(await item)
            return first, second

        (first, second), _ = await _run_live(text, consumer)
        assert first == [1, 2, 3]
        assert second == [1, 2, 3]

    async def test_parallel_consumers_both_see_all_items(self):
        text = '{"logs":["x","y","z"]}'
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)

        async def ingest():
            for ch in text:
                ingestor.feed(ch)
                await asyncio.sleep(0)
            ingestor.finish()

        async def consume():
            out = []
            async for item in root["logs"]:
                out.append(await item)
            return out

        a, b, _ = await asyncio.gather(consume(), consume(), ingest())
        assert a == ["x", "y", "z"]
        assert b == ["x", "y", "z"]

    async def test_await_array_returns_materialized_list(self):
        root = await _ingest_text('{"logs":[10,20,30]}')
        assert await root["logs"] == [10, 20, 30]

    async def test_nested_snapshot_includes_array_and_object_children(self):
        root = await _ingest_text(
            '{"user":{"name":"A","tags":["t1","t2"],"meta":{"n":2}}}'
        )
        user = await root["user"]
        assert user == {"name": "A", "tags": ["t1", "t2"], "meta": {"n": 2}}

    async def test_array_of_objects_streams_full_items(self):
        text = '{"rows":[{"id":1},{"id":2}]}'

        async def consumer(root):
            out = []
            async for item in root["rows"]:
                out.append(await item)
            return out

        rows, _ = await _run_live(text, consumer)
        assert rows == [{"id": 1}, {"id": 2}]

    async def test_async_for_yields_item_handles_by_default(self):
        text = '{"rows":[{"id":1},{"id":2}]}'
        root, ingest = _setup(text, chunk_size=1)

        async def consume():
            ids = []
            async for item in root["rows"]:
                assert isinstance(item, AsyncJsonNode)
                ids.append(await item["id"])
            return ids

        ids, _ = await asyncio.gather(consume(), ingest())
        assert ids == [1, 2]

    async def test_values_iterates_completed_values(self):
        text = '{"rows":[{"id":1},{"id":2}]}'
        root, ingest = _setup(text, chunk_size=1)

        async def consume():
            out = []
            async for item in root["rows"].values():
                out.append(item)
            return out

        rows, _ = await asyncio.gather(consume(), ingest())
        assert rows == [{"id": 1}, {"id": 2}]

    async def test_multidigit_numbers_not_truncated_under_char_streaming(self):
        text = '{"logs":[10,20,30]}'

        async def consumer(root):
            out = []
            async for item in root["logs"]:
                out.append(await item)
            return out

        streamed, _ = await _run_live(text, consumer, chunk_size=1)
        assert streamed == [10, 20, 30]

    async def test_mixed_scalars_in_array(self):
        text = '{"vals":[true,false,null,42,"x"]}'

        async def consumer(root):
            out = []
            async for item in root["vals"]:
                out.append(await item)
            return out

        vals, _ = await _run_live(text, consumer)
        assert vals == [True, False, None, 42, "x"]

    async def test_late_subscriber_replays_fully_after_finish(self):
        root = await _ingest_text('{"logs":["m","n","o"]}')
        seen = []
        async for item in root["logs"]:
            seen.append(await item)
        assert seen == ["m", "n", "o"]

    async def test_two_top_level_objects_resolve_independently(self):
        root = await _ingest_text('{"a":{"k":1},"b":{"k":2}}')
        assert await root["a"] == {"k": 1}
        assert await root["b"] == {"k": 2}

    async def test_object_key_named_item_is_not_treated_as_array_item(self):
        root = await _ingest_text('{"item": {"value": 7}}')
        assert await root["item"] == {"value": 7}

    async def test_object_key_with_dot_round_trips(self):
        root = await _ingest_text('{"a.b": 1, "nested": {"x.y": 2}}')
        assert await root["a.b"] == 1
        assert await root["nested"] == {"x.y": 2}

    async def test_finish_on_incomplete_json_propagates_error(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"logs": [1, 2')
        try:
            ingestor.finish()
        except Exception:
            pass
        else:
            raise AssertionError("Expected finish() to fail on incomplete JSON.")

        with pytest.raises(Exception):
            await root["logs"]

    async def test_late_subscriber_keeps_full_replay(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        for chunk in ('{"logs":[1,2,3,4]}',):
            ingestor.feed(chunk)
        ingestor.finish()

        out = []
        async for item in root["logs"]:
            out.append(await item)
        assert out == [1, 2, 3, 4]

    async def test_missing_key_fails_after_successful_finish(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"user":{"name":"Alice"},"logs":["a"]}')
        ingestor.finish()

        with pytest.raises(KeyError, match="Missing key"):
            await root["use"]

    async def test_existing_key_still_resolves_after_finish(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"user":{"name":"Alice"}}')
        ingestor.finish()
        assert await root["user"] == {"name": "Alice"}

    async def test_new_key_after_close_with_error_fails_immediately(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"logs": [1, 2')
        try:
            ingestor.finish()
        except Exception:
            pass

        # Must raise KeyError (or similar), NOT TimeoutError.
        # If it hangs and only TimeoutError fires, the bug is present.
        try:
            await asyncio.wait_for(root["never_existed"], timeout=0.5)
            raise AssertionError("Should have raised")
        except asyncio.TimeoutError:
            raise AssertionError(
                "Node hung instead of failing immediately — tree not sealed after close_with_error"
            )
        except (KeyError, Exception) as e:
            if isinstance(e, AssertionError):
                raise
            pass  # expected: immediate failure


class TestExoticCases:
    async def test_empty_object_and_empty_array(self):
        root = await _ingest_text('{"a":{},"b":[],"c":"ok"}')
        assert await root["a"] == {}
        assert await root["b"] == []
        assert await root["c"] == "ok"

    async def test_nested_arrays_matrix(self):
        text = '{"matrix":[[1,2],[3,4]]}'
        root, ingest = _setup(text)

        async def consume():
            out = []
            async for row in root["matrix"]:
                out.append(await row)
            return out

        rows, _ = await asyncio.gather(consume(), ingest())
        assert rows == [[1, 2], [3, 4]]

    async def test_top_level_array(self):
        text = '[1,"two",true]'
        root, ingest = _setup(text)

        async def consume():
            out = []
            async for item in root:
                out.append(await item)
            return out

        items, _ = await asyncio.gather(consume(), ingest())
        assert items == [1, "two", True]

    async def test_top_level_scalar(self):
        root = await _ingest_text('"hello"')
        assert await root == "hello"

    async def test_top_level_number(self):
        root = await _ingest_text("42")
        assert await root == 42

    async def test_top_level_bool(self):
        root = await _ingest_text("true")
        assert await root is True

    async def test_top_level_null(self):
        root = await _ingest_text("null")
        assert await root is None

    async def test_deeply_nested_object(self):
        text = '{"a":{"b":{"c":{"d":"deep"}}}}'
        root = await _ingest_text(text)
        assert await root["a"] == {"b": {"c": {"d": "deep"}}}
        assert await root["a"]["b"] == {"c": {"d": "deep"}}
        assert await root["a"]["b"]["c"] == {"d": "deep"}
        assert await root["a"]["b"]["c"]["d"] == "deep"

    async def test_unicode_keys_and_values(self):
        text = '{"émoji":"🎉","日本語":"テスト"}'
        root = await _ingest_text(text)
        assert await root["émoji"] == "🎉"
        assert await root["日本語"] == "テスト"

    async def test_concurrent_await_same_key(self):
        text = '{"name":"Alice"}'
        root, ingest = _setup(text)

        async def c1():
            return await root["name"]

        async def c2():
            return await root["name"]

        r1, r2, _ = await asyncio.gather(c1(), c2(), ingest())
        assert r1 == "Alice"
        assert r2 == "Alice"

    async def test_string_containing_json(self):
        import json

        inner = json.dumps({"nested": True})
        text = json.dumps({"payload": inner})
        root = await _ingest_text(text)
        result = await root["payload"]
        assert result == '{"nested": true}'

    async def test_large_object_50_keys(self):
        import json

        data = {f"key_{i}": i for i in range(50)}
        text = json.dumps(data)
        root = await _ingest_text(text, chunk_size=10)
        for i in range(50):
            assert await root[f"key_{i}"] == i

    async def test_escaped_strings(self):
        text = r'{"a":"line1\nline2","b":"say \"hi\""}'
        root = await _ingest_text(text)
        assert await root["a"] == "line1\nline2"
        assert await root["b"] == 'say "hi"'

    async def test_mixed_empty_containers_in_array(self):
        text = '{"items":[{},[],"x",null,42]}'
        root, ingest = _setup(text)

        async def consume():
            out = []
            async for item in root["items"]:
                out.append(await item)
            return out

        items, _ = await asyncio.gather(consume(), ingest())
        assert items == [{}, [], "x", None, 42]

    async def test_array_of_arrays_of_objects(self):
        text = '{"data":[[{"id":1}],[{"id":2}]]}'
        root, ingest = _setup(text)

        async def consume():
            out = []
            async for group in root["data"]:
                out.append(await group)
            return out

        groups, _ = await asyncio.gather(consume(), ingest())
        assert groups == [[{"id": 1}], [{"id": 2}]]

    async def test_object_after_array_at_same_level(self):
        text = '{"arr":[1,2],"obj":{"k":3},"arr2":[4]}'
        root, ingest = _setup(text)

        async def consume():
            a = []
            async for item in root["arr"]:
                a.append(await item)
            obj = await root["obj"]
            a2 = []
            async for item in root["arr2"]:
                a2.append(await item)
            return a, obj, a2

        (a, obj, a2), _ = await asyncio.gather(consume(), ingest())
        assert a == [1, 2]
        assert obj == {"k": 3}
        assert a2 == [4]

    async def test_floats_and_scientific_notation(self):
        text = '{"pi":3.14159,"big":1e10,"neg":-0.5}'
        root = await _ingest_text(text)
        import math

        assert math.isclose(await root["pi"], 3.14159)
        assert await root["big"] == 1e10
        assert await root["neg"] == -0.5


class TestAdversarial:
    async def test_await_resolved_key_then_iterate_array_child(self):
        """Await an object node, then separately iterate its array child."""
        text = '{"user":{"name":"A","tags":["x","y"]}}'
        root, ingest = _setup(text)

        async def consume():
            user = await root["user"]
            assert user == {"name": "A", "tags": ["x", "y"]}
            tags = []
            async for t in root["user"]["tags"]:
                tags.append(await t)
            return tags

        tags, _ = await asyncio.gather(consume(), ingest())
        assert tags == ["x", "y"]

    async def test_interleaved_array_and_object_access(self):
        """Start iterating array, mid-iteration await a sibling key."""
        text = '{"logs":["a","b","c"],"count":3}'
        root, ingest = _setup(text)

        async def consume():
            first_log = None
            async for item in root["logs"]:
                if first_log is None:
                    first_log = await item
                    count = await root["count"]
            return first_log, count

        (first_log, count), _ = await asyncio.gather(consume(), ingest())
        assert first_log == "a"
        assert count == 3

    async def test_100_item_array_char_by_char(self):
        import json

        data = {"nums": list(range(100))}
        text = json.dumps(data)
        root, ingest = _setup(text, chunk_size=1)

        async def consume():
            out = []
            async for item in root["nums"]:
                out.append(await item)
            return out

        items, _ = await asyncio.gather(consume(), ingest())
        assert items == list(range(100))

    async def test_triple_nested_array(self):
        text = '{"cube":[[[1,2],[3,4]],[[5,6],[7,8]]]}'
        root, ingest = _setup(text)

        async def consume():
            out = []
            async for layer in root["cube"]:
                out.append(await layer)
            return out

        cube, _ = await asyncio.gather(consume(), ingest())
        assert cube == [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]

    async def test_empty_string_key_and_value(self):
        text = '{"":"","a":"b"}'
        root = await _ingest_text(text)
        assert await root[""] == ""
        assert await root["a"] == "b"

    async def test_key_named_item(self):
        """Key literally named 'item' must not collide with array semantics."""
        text = '{"item":"val","items":[1]}'
        root, ingest = _setup(text)

        async def consume():
            v = await root["item"]
            items = []
            async for i in root["items"]:
                items.append(await i)
            return v, items

        (v, items), _ = await asyncio.gather(consume(), ingest())
        assert v == "val"
        assert items == [1]

    async def test_two_consumers_staggered_start(self):
        """Second consumer starts after first has already read some items."""
        text = '{"logs":["a","b","c","d","e"]}'
        root, ingest = _setup(text)

        barrier = asyncio.Event()

        async def fast_consumer():
            out = []
            async for item in root["logs"]:
                out.append(await item)
                if len(out) == 2:
                    barrier.set()
            return out

        async def slow_consumer():
            await barrier.wait()
            out = []
            async for item in root["logs"]:
                out.append(await item)
            return out

        fast, slow, _ = await asyncio.gather(fast_consumer(), slow_consumer(), ingest())
        assert fast == ["a", "b", "c", "d", "e"]
        assert slow == ["a", "b", "c", "d", "e"]

    async def test_await_array_as_value_while_also_iterating(self):
        """One consumer awaits the array (gets list), another iterates it."""
        text = '{"nums":[10,20,30]}'
        root, ingest = _setup(text)

        async def awaiter():
            return await root["nums"]

        async def streamer():
            out = []
            async for item in root["nums"]:
                out.append(await item)
            return out

        awaited, streamed, _ = await asyncio.gather(awaiter(), streamer(), ingest())
        assert awaited == [10, 20, 30]
        assert streamed == [10, 20, 30]

    async def test_single_chunk_large_json(self):
        """Entire JSON arrives in one big chunk — no partial parses."""
        import json

        data = {
            "users": [
                {"name": f"user_{i}", "scores": list(range(i, i + 3))}
                for i in range(10)
            ],
            "meta": {"total": 10, "tags": ["a", "b"]},
        }
        text = json.dumps(data)
        root = await _ingest_text(text, chunk_size=len(text))
        meta = await root["meta"]
        assert meta == {"total": 10, "tags": ["a", "b"]}
        users = await root["users"]
        assert len(users) == 10
        assert users[0] == {"name": "user_0", "scores": [0, 1, 2]}

    async def test_null_values_everywhere(self):
        text = '{"a":null,"b":[null,null],"c":{"d":null}}'
        root = await _ingest_text(text)
        assert await root["a"] is None
        assert await root["b"] == [None, None]
        assert await root["c"] == {"d": None}

    async def test_object_inside_array_inside_object_inside_array(self):
        """4-deep alternating: array > obj > array > obj."""
        text = '{"rows":[{"cells":[{"v":1},{"v":2}]},{"cells":[{"v":3}]}]}'
        root, ingest = _setup(text)

        async def consume():
            out = []
            async for row in root["rows"]:
                out.append(await row)
            return out

        rows, _ = await asyncio.gather(consume(), ingest())
        assert rows == [
            {"cells": [{"v": 1}, {"v": 2}]},
            {"cells": [{"v": 3}]},
        ]

    async def test_slow_consumer_with_fast_producer_no_data_loss(self):
        """Producer finishes before consumer starts iterating."""
        import json

        data = {"items": list(range(20))}
        text = json.dumps(data)
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed(text)
        ingestor.finish()
        # All data is already ingested; consumer starts late
        out = []
        async for item in root["items"]:
            out.append(await item)
        assert out == list(range(20))

    async def test_three_parallel_iterators_plus_awaiter(self):
        text = '{"arr":[1,2,3,4,5]}'
        root, ingest = _setup(text)

        async def iterate():
            out = []
            async for i in root["arr"]:
                out.append(await i)
            return out

        async def await_it():
            return await root["arr"]

        r1, r2, r3, r4, _ = await asyncio.gather(
            iterate(), iterate(), iterate(), await_it(), ingest()
        )
        expected = [1, 2, 3, 4, 5]
        assert r1 == expected
        assert r2 == expected
        assert r3 == expected
        assert r4 == expected

    async def test_byte_chunks_instead_of_str(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        for chunk in [b'{"na', b'me":', b' "Bo', b'b"}']:
            ingestor.feed(chunk)
        ingestor.finish()
        assert await root["name"] == "Bob"

    async def test_many_small_arrays(self):
        import json

        data = {f"a{i}": [i, i + 1] for i in range(20)}
        text = json.dumps(data)
        root = await _ingest_text(text, chunk_size=3)
        for i in range(20):
            assert await root[f"a{i}"] == [i, i + 1]


class TestConfidenceGaps:
    async def test_scalar_inside_object_inside_array_char_by_char(self):
        """Exercises scalar propagation in nested array/object parsing."""
        text = '{"rows":[{"name":"Alice","age":30},{"name":"Bob","age":25}]}'
        root, ingest = _setup(text, chunk_size=1)

        async def consume():
            out = []
            async for row in root["rows"]:
                out.append(await row)
            return out

        rows, _ = await asyncio.gather(consume(), ingest())
        assert rows == [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]

    async def test_deeply_nested_scalars_in_array_objects(self):
        """Scalars inside objects inside arrays inside objects, 3 levels deep."""
        text = '{"data":[{"tags":[{"label":"x","weight":1.5}]}]}'
        root, ingest = _setup(text, chunk_size=1)

        async def consume():
            out = []
            async for item in root["data"]:
                out.append(await item)
            return out

        data, _ = await asyncio.gather(consume(), ingest())
        assert data == [{"tags": [{"label": "x", "weight": 1.5}]}]

    async def test_live_slow_consumer_still_sees_all_items(self):
        """Slow consumer receives all items with unbounded replay."""
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)

        received = []
        barrier = asyncio.Event()

        async def slow_consumer():
            async for item in root["nums"]:
                received.append(await item)
                if len(received) == 1:
                    barrier.set()
                    await asyncio.sleep(0)

        async def producer():
            ingestor.feed('{"nums":[')
            for i in range(1, 6):
                ingestor.feed(f"{i},")
                await asyncio.sleep(0)
            ingestor.feed("6]}")
            ingestor.finish()

        await asyncio.gather(slow_consumer(), producer())
        assert received == [1, 2, 3, 4, 5, 6]

    async def test_late_subscriber_gets_full_history(self):
        """Late subscriber after ingestion still sees the full history."""
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"nums":[1,2,3,4,5,6,7,8]}')
        ingestor.finish()

        out = []
        async for item in root["nums"]:
            out.append(await item)
        assert out == [1, 2, 3, 4, 5, 6, 7, 8]

    async def test_sync_bulk_feed_keeps_full_history(self):
        """Sync bulk feed still preserves full history for iteration."""
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)

        async def consumer():
            out = []
            async for item in root["nums"]:
                out.append(await item)
            return out

        async def producer():
            ingestor.feed('{"nums":[1,2,3,4,5]}')
            ingestor.finish()

        result, _ = await asyncio.gather(consumer(), producer())
        assert result == [1, 2, 3, 4, 5]

    async def test_async_drip_feed_keeps_all(self):
        """With async yields between items, consumer receives all items."""
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)

        async def consumer():
            out = []
            async for item in root["nums"]:
                out.append(await item)
            return out

        async def producer():
            for chunk in ['{"nums":[', "1,", "2,", "3,", "4,", "5]}"]:
                ingestor.feed(chunk)
                await asyncio.sleep(0)
            ingestor.finish()

        result, _ = await asyncio.gather(consumer(), producer())
        assert result == [1, 2, 3, 4, 5]

    async def test_await_and_async_for_on_object_node_concurrently(self):
        """One task awaits object node (gets dict), another tries async for (gets nothing)."""
        text = '{"user":{"name":"Alice","age":30}}'
        root, ingest = _setup(text)

        async def awaiter():
            return await root["user"]

        async def iterator():
            out = []
            async for item in root["user"]:
                out.append(item)
            return out

        awaited, iterated, _ = await asyncio.gather(awaiter(), iterator(), ingest())
        assert awaited == {"name": "Alice", "age": 30}
        # Object nodes don't push stream items, so iterator gets nothing
        assert iterated == []


class TestSyncValue:
    """Tests for RNode.value — synchronous access after parsing is complete."""

    def test_scalar_value(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('"hello"')
        ingestor.finish()
        assert root.value == "hello"

    def test_object_value(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"name": "Alice", "age": 30}')
        ingestor.finish()
        assert root["name"].value == "Alice"
        assert root["age"].value == 30

    def test_nested_object_value(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"user": {"name": "Bob", "tags": ["a", "b"]}}')
        ingestor.finish()
        assert root["user"].value == {"name": "Bob", "tags": ["a", "b"]}
        assert root["user"]["name"].value == "Bob"

    def test_array_value(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"scores": [10, 20, 30]}')
        ingestor.finish()
        assert root["scores"].value == [10, 20, 30]

    def test_value_raises_before_resolve(self):
        root = AsyncJsonNode()
        with pytest.raises(LookupError, match="not yet resolved"):
            root["name"].value

    def test_value_raises_on_missing_key(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"name": "Alice"}')
        ingestor.finish()
        with pytest.raises(KeyError, match="Missing key"):
            root["nonexistent"].value

    def test_value_raises_on_parse_error(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"name": ')
        try:
            ingestor.finish()
        except Exception:
            pass
        with pytest.raises(Exception):
            root["name"].value

    def test_null_value(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"x": null}')
        ingestor.finish()
        assert root["x"].value is None

    def test_resolved_property(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        assert not root["name"].resolved
        ingestor.feed('{"name": "Alice"}')
        ingestor.finish()
        assert root["name"].resolved


class TestSyncIteration:
    """Tests for RNode.__iter__ — synchronous iteration after parsing."""

    def test_iterate_array(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"items": [1, 2, 3]}')
        ingestor.finish()
        assert list(root["items"]) == [1, 2, 3]

    def test_iterate_array_of_objects(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"rows": [{"id": 1}, {"id": 2}]}')
        ingestor.finish()
        assert list(root["rows"]) == [{"id": 1}, {"id": 2}]

    def test_iterate_empty_array(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"items": []}')
        ingestor.finish()
        assert list(root["items"]) == []

    def test_iterate_before_finish_raises(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"items": [1, 2')
        with pytest.raises(RuntimeError, match="Stream not complete"):
            list(root["items"])

    def test_iterate_top_level_array(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed("[10, 20, 30]")
        ingestor.finish()
        assert list(root) == [10, 20, 30]

    def test_for_loop(self):
        root = AsyncJsonNode()
        ingestor = AsyncJsonFeed(root)
        ingestor.feed('{"tags": ["a", "b", "c"]}')
        ingestor.finish()
        out = []
        for tag in root["tags"]:
            out.append(tag)
        assert out == ["a", "b", "c"]


class TestJsontapWithAsyncSource:
    """Tests for jsontap(async_source) — returns RNode, auto-starts task."""

    async def test_basic_async_source(self):
        async def source():
            for chunk in ['{"name":', '"Alice",', '"age":30}']:
                yield chunk

        root = jsontap(source())
        assert await root["name"] == "Alice"
        assert await root["age"] == 30

    async def test_stream_array(self):
        async def source():
            for chunk in ['{"items":[', "1,2,", "3]}"]:
                yield chunk
                await asyncio.sleep(0)

        root = jsontap(source())
        items = []
        async for item in root["items"]:
            items.append(await item)
        assert items == [1, 2, 3]

    async def test_source_error_propagates(self):
        async def bad_source():
            yield '{"name":'
            raise ValueError("connection lost")

        root = jsontap(bad_source())
        with pytest.raises(ValueError, match="connection lost"):
            await root["name"]

    async def test_partial_read(self):
        async def source():
            yield '{"a":1,"b":2,"c":3}'

        root = jsontap(source())
        assert await root["a"] == 1

    async def test_slow_source_live_consumption(self):
        async def slow_source():
            chunks = [
                '{"intent":"refund",',
                '"steps":["verify",',
                '"check",',
                '"refund"],',
                '"done":true}',
            ]
            for c in chunks:
                yield c
                await asyncio.sleep(0)

        root = jsontap(slow_source())

        intent = await root["intent"]
        assert intent == "refund"

        steps = []
        async for step in root["steps"]:
            steps.append(await step)
        assert steps == ["verify", "check", "refund"]

        assert await root["done"] is True

    async def test_task_stored_on_root(self):
        async def source():
            yield '{"x": 1}'

        root = jsontap(source())
        assert hasattr(root, "_task")
        await root._task


class TestJsontapWithSyncSource:
    """Tests for jsontap(sync_source) — parses eagerly, returns RNode."""

    def test_basic_sync_source(self):
        root = jsontap(['{"name":', '"Alice",', '"age":30}'])
        assert root["name"].value == "Alice"
        assert root["age"].value == 30

    def test_sync_iterate(self):
        root = jsontap(['{"items":[1,2,3]}'])
        assert list(root["items"]) == [1, 2, 3]

    def test_sync_generator_source(self):
        def gen():
            yield '{"x":'
            yield "42}"

        root = jsontap(gen())
        assert root["x"].value == 42

    def test_sync_bytes(self):
        root = jsontap([b'{"k":', b'"v"}'])
        assert root["k"].value == "v"

    def test_sync_bad_json(self):
        with pytest.raises(Exception):
            jsontap(['{"name": '])

    def test_nested_sync(self):
        root = jsontap(['{"user":{"name":"Bob","scores":[10,20]}}'])
        assert root["user"]["name"].value == "Bob"
        assert list(root["user"]["scores"]) == [10, 20]
        assert root["user"].value == {"name": "Bob", "scores": [10, 20]}


class TestJsontapManualFeed:
    """Tests for jsontap() — returns (root, feed, finish) tuple."""

    def test_basic_manual_feed(self):
        root, feed, finish = jsontap()
        feed('{"name": "Alice"}')
        finish()
        assert root["name"].value == "Alice"

    def test_incremental_feed(self):
        root, feed, finish = jsontap()
        feed('{"na')
        feed('me":')
        feed('"Bob"}')
        finish()
        assert root["name"].value == "Bob"

    def test_feed_and_sync_iterate(self):
        root, feed, finish = jsontap()
        feed('{"nums": [1, 2, 3]}')
        finish()
        assert list(root["nums"]) == [1, 2, 3]

    async def test_feed_then_await(self):
        root, feed, finish = jsontap()
        feed('{"name": "Eve"}')
        finish()
        assert await root["name"] == "Eve"

    def test_dotted_key(self):
        root, feed, finish = jsontap()
        feed('{"a.b": 1}')
        finish()
        assert root["a.b"].value == 1

import asyncio
import ijson

_VALUE_EVENTS = frozenset({"string", "number", "boolean", "null"})
_UNSET = object()


class RNode:
    def __init__(self, *, path=()):
        self.children = {}
        self.path = path
        self.sealed = False
        self.stream_items = []
        self.stream_done = False
        self.stream_error = None
        self._future = None
        self._value = _UNSET
        self._exception = None
        self._stream_waiters = []

    @property
    def resolved(self):
        return self._value is not _UNSET or self._exception is not None

    def _ensure_future(self):
        if self._future is None:
            self._future = asyncio.Future()
            if self._value is not _UNSET:
                self._future.set_result(self._value)
            elif self._exception is not None:
                self._future.set_exception(self._exception)
        return self._future

    def __getitem__(self, key):
        if key not in self.children:
            child = RNode(path=(*self.path, key))
            if self.sealed:
                key_path = ".".join(child.path)
                child.fail(KeyError(f"Missing key in parsed JSON: {key_path}"))
                child.sealed = True
            self.children[key] = child
        return self.children[key]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    @property
    def value(self):
        """Synchronous access to the resolved value.

        Raises LookupError if the value hasn't been parsed yet.
        """
        if self._value is not _UNSET:
            return self._value
        if self._exception is not None:
            raise self._exception
        raise LookupError(
            "Value not yet resolved. "
            "Use 'await node' in async code, or ensure parsing is complete."
        )

    def resolve(self, value):
        if self.resolved:
            return
        self._value = value
        if self._future is not None and not self._future.done():
            self._future.set_result(value)

    def push_stream(self, value):
        self.stream_items.append(value)
        self._wake_stream_waiters()

    def end_stream(self, final_value=None):
        self.stream_done = True
        self.resolve(list(self.stream_items) if final_value is None else final_value)
        self._wake_stream_waiters()

    def fail(self, exc):
        self.stream_error = exc
        self.stream_done = True
        if not self.resolved:
            self._exception = exc
            if self._future is not None and not self._future.done():
                self._future.set_exception(exc)
        self._wake_stream_waiters()

    def _wake_stream_waiters(self):
        for waiter in self._stream_waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._stream_waiters.clear()

    def __await__(self):
        return self._ensure_future().__await__()

    def __aiter__(self):
        return _StreamCursor(self)

    def __iter__(self):
        """Synchronous iteration over completed stream items."""
        if not self.stream_done:
            raise RuntimeError(
                "Stream not complete. "
                "Use 'async for' in async code, or ensure parsing is complete."
            )
        if self.stream_error is not None:
            raise self.stream_error
        return iter(self.stream_items)


class _StreamCursor:
    def __init__(self, node):
        self.node = node
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            if self.index < len(self.node.stream_items):
                value = self.node.stream_items[self.index]
                self.index += 1
                return value

            if self.node.stream_error is not None:
                raise self.node.stream_error

            if self.node.stream_done:
                raise StopAsyncIteration

            waiter = asyncio.get_running_loop().create_future()
            self.node._stream_waiters.append(waiter)
            await waiter


class JSONFeed:
    def __init__(self, root_node):
        self.root = root_node
        self._events = ijson.sendable_list()
        self._parser = ijson.parse_coro(self._events)
        self._container_stack = []
        self._closed = False

    def _fail_all_nodes(self, node, exc):
        node.fail(exc)
        for child in node.children.values():
            self._fail_all_nodes(child, exc)

    def _seal_tree(self, node):
        node.sealed = True
        if not node.stream_done:
            node.stream_done = True
            node._wake_stream_waiters()
        for child in node.children.values():
            self._seal_tree(child)

    def _fail_unresolved_nodes(self, node):
        if not node.resolved:
            key_path = ".".join(node.path) if node.path else "<root>"
            node.fail(KeyError(f"Missing key in parsed JSON: {key_path}"))
        for child in node.children.values():
            self._fail_unresolved_nodes(child)

    def close_with_error(self, exc):
        if self._closed:
            return
        self._closed = True
        self._fail_all_nodes(self.root, exc)
        self._seal_tree(self.root)

    def feed(self, chunk):
        if self._closed:
            raise RuntimeError("Cannot feed after parser is closed.")

        try:
            data = (
                chunk
                if isinstance(chunk, (bytes, bytearray))
                else chunk.encode("utf-8")
            )
            self._parser.send(data)
        except ijson.IncompleteJSONError:
            return
        except Exception as exc:
            self.close_with_error(exc)
            raise

        for prefix, event, value in self._events:
            self._apply_event(prefix, event, value)
        self._events.clear()

    def finish(self):
        if self._closed:
            return
        try:
            self._parser.close()
        except ijson.IncompleteJSONError:
            self.close_with_error(
                ijson.IncompleteJSONError("Incomplete JSON at stream end")
            )
            raise
        except Exception as exc:
            self.close_with_error(exc)
            raise

        for prefix, event, value in self._events:
            self._apply_event(prefix, event, value)
        self._events.clear()
        self._fail_unresolved_nodes(self.root)
        self._seal_tree(self.root)
        self._closed = True

    def _current_parent(self):
        return self._container_stack[-1] if self._container_stack else None

    def _next_array_item_node(self, parent):
        index = parent["next_index"]
        parent["next_index"] += 1
        return parent["node"][str(index)]

    def _start_container(self, kind):
        parent = self._current_parent()
        value = {} if kind == "map" else []

        if parent is None:
            node = self.root
        elif parent["type"] == "map":
            key = parent["key"]
            if key is None:
                raise RuntimeError("Map value started without a map key.")
            node = parent["node"][key]
            parent["value"][key] = value
            parent["key"] = None
        else:
            node = self._next_array_item_node(parent)
            parent["value"].append(value)

        self._container_stack.append(
            {"type": kind, "value": value, "node": node, "key": None, "next_index": 0}
        )

    def _consume_scalar(self, value):
        parent = self._current_parent()
        if parent is None:
            self.root.resolve(value)
            return

        if parent["type"] == "map":
            key = parent["key"]
            if key is None:
                raise RuntimeError("Scalar map value arrived without a map key.")
            parent["value"][key] = value
            parent["node"][key].resolve(value)
            parent["key"] = None
            return

        parent["value"].append(value)
        item_node = self._next_array_item_node(parent)
        item_node.resolve(value)
        parent["node"].push_stream(value)

    def _complete_container(self, expected_type):
        if not self._container_stack:
            raise RuntimeError(f"Unexpected end of {expected_type}.")

        current = self._container_stack.pop()
        if current["type"] != expected_type:
            raise RuntimeError(
                f"Mismatched container close: expected {current['type']} got {expected_type}."
            )

        completed = current["value"]
        node = current["node"]
        if expected_type == "map":
            node.resolve(completed)
        else:
            node.end_stream(completed)

        parent = self._current_parent()
        if parent is not None and parent["type"] == "array":
            parent["node"].push_stream(completed)

    def _apply_event(self, prefix, event, value):
        if event == "start_map":
            self._start_container("map")
            return

        if event == "map_key":
            if self._container_stack and self._container_stack[-1]["type"] == "map":
                self._container_stack[-1]["key"] = value
            return

        if event == "start_array":
            self._start_container("array")
            return

        if event == "end_map":
            self._complete_container("map")
            return

        if event == "end_array":
            self._complete_container("array")
            return

        if event not in _VALUE_EVENTS:
            return

        self._consume_scalar(value)


def jsontap(source=None):
    """Create a reactive JSON root.

    With an async source — starts a background task, returns the root node:

        root = jsontap(llm_stream())
        name = await root.user.name
        async for item in root.items:
            process(item)

    With a sync source — parses eagerly, returns the root node:

        root = jsontap(chunks)
        name = root.user.name.value
        for item in root.items:
            process(item)

    Without a source — returns (root, feed, finish) for manual feeding:

        root, feed, finish = jsontap()
        feed('{"name": "Alice"}')
        finish()
        name = root.name.value
    """
    root = RNode()
    ingestor = JSONFeed(root)

    if source is None:
        return root, ingestor.feed, ingestor.finish

    if hasattr(source, "__aiter__"):

        async def _drive():
            try:
                async for chunk in source:
                    ingestor.feed(chunk)
                ingestor.finish()
            except Exception as exc:
                ingestor.close_with_error(exc)

        root._task = asyncio.create_task(_drive())
        return root

    try:
        for chunk in source:
            ingestor.feed(chunk)
        ingestor.finish()
    except Exception as exc:
        ingestor.close_with_error(exc)
        raise

    return root

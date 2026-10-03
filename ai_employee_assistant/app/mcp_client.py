import asyncio
import os
from contextlib import AsyncExitStack
from typing import Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class MCPClientWrapper:
    """Timeout-aware MCP stdio client with a safe shared lifecycle.

    AnyIO requires the task that enters an MCP stdio context to also exit it.
    FastAPI requests run in different tasks, so this wrapper owns each MCP
    session in one background task and sends list/call requests through a queue.
    """

    def __init__(
        self,
        command: str,
        args: list,
        *,
        env: Optional[dict] = None,
        connect_timeout: float = 10.0,
        tool_timeout: float = 30.0,
    ):
        self.command = command
        self.args = args
        self.extra_env = env or {}
        self.connect_timeout = connect_timeout
        self.tool_timeout = tool_timeout
        self._session = None
        self._tools_cache = None
        self._queue = None
        self._runner_task = None
        self._connect_lock = asyncio.Lock()
        self.last_error = None

    @staticmethod
    def _resolve_future(future, *, result=None, error=None):
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    async def _run_session(self, ready):
        env = os.environ.copy()
        env.update(self.extra_env)
        try:
            async with AsyncExitStack() as stack:
                params = StdioServerParameters(
                    command=self.command,
                    args=self.args,
                    env=env,
                )
                transport = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(*transport))
                await session.initialize()
                self._session = session
                self.last_error = None
                self._resolve_future(ready, result=True)

                while True:
                    operation, payload, future = await self._queue.get()
                    if operation == "stop":
                        self._resolve_future(future, result=True)
                        break
                    try:
                        if operation == "list_tools":
                            response = await session.list_tools()
                            value = response.tools
                        elif operation == "call_tool":
                            value = await session.call_tool(
                                payload["name"], arguments=payload["arguments"]
                            )
                        else:
                            raise ValueError(f"Unknown MCP operation: {operation}")
                        self._resolve_future(future, result=value)
                    except BaseException as exc:
                        self._resolve_future(future, error=exc)
        except BaseException as exc:
            self.last_error = str(exc) or type(exc).__name__
            self._resolve_future(ready, error=exc)
            raise
        finally:
            self._session = None

    async def connect(self):
        if self._session is not None:
            return

        async with self._connect_lock:
            if self._session is not None:
                return
            if self._runner_task and self._runner_task.done():
                try:
                    self._runner_task.result()
                except BaseException:
                    pass
                self._runner_task = None

            loop = asyncio.get_running_loop()
            self._queue = asyncio.Queue()
            ready = loop.create_future()
            self._runner_task = asyncio.create_task(self._run_session(ready))
            try:
                await asyncio.wait_for(
                    asyncio.shield(ready), timeout=self.connect_timeout
                )
            except BaseException:
                if self._runner_task and not self._runner_task.done():
                    self._runner_task.cancel()
                    try:
                        await self._runner_task
                    except BaseException:
                        pass
                self._runner_task = None
                self._queue = None
                raise

    async def _request(self, operation: str, payload: Optional[dict] = None):
        await self.connect()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put((operation, payload or {}, future))
        return await asyncio.wait_for(future, timeout=self.tool_timeout)

    async def get_tools(self, refresh: bool = False):
        if self._tools_cache is not None and not refresh:
            return self._tools_cache
        self._tools_cache = await self._request("list_tools")
        return self._tools_cache

    async def call_tool(self, name: str, args: dict):
        return await self._request(
            "call_tool", {"name": name, "arguments": args}
        )

    async def disconnect(self):
        task = self._runner_task
        queue = self._queue
        self._runner_task = None
        self._queue = None
        self._session = None
        self._tools_cache = None
        if not task:
            return
        if task.done():
            try:
                task.result()
            except BaseException:
                pass
            return

        loop = asyncio.get_running_loop()
        stopped = loop.create_future()
        await queue.put(("stop", {}, stopped))
        try:
            await asyncio.wait_for(stopped, timeout=self.tool_timeout)
            await asyncio.wait_for(task, timeout=self.tool_timeout)
        except BaseException:
            task.cancel()
            try:
                await task
            except BaseException:
                pass

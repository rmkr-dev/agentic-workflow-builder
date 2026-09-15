"""Concrete Agent Framework executors (annotations must not be postponed)."""

from typing import Never

from agent_framework import Executor, WorkflowContext, handler

from agentforge.runtimes.base.helpers import llm_respond


def make_passthrough(executor_id: str = "af_start") -> Executor:
    class StartExec(Executor):
        @handler
        async def process(self, text: str, ctx: WorkflowContext[str]) -> None:
            await ctx.send_message(str(text))

    return StartExec(id=executor_id)


def make_join(executor_id: str = "af_join") -> Executor:
    class JoinExec(Executor):
        @handler
        async def process(self, messages: list[str], ctx: WorkflowContext[Never, str]) -> None:
            await ctx.yield_output(" | ".join(str(m) for m in messages))

    return JoinExec(id=executor_id)


def make_agent_executor(node_id: str, system_prompt: str, *, final: bool = False) -> Executor:
    prompt = system_prompt
    agent_key = node_id

    if final:

        class FinalAgentExec(Executor):
            @handler
            async def process(self, text: str, ctx: WorkflowContext[Never, str]) -> None:
                out = llm_respond(prompt, str(text), agent_id=agent_key)
                await ctx.yield_output(out)

        return FinalAgentExec(id=node_id)

    class AgentExec(Executor):
        @handler
        async def process(self, text: str, ctx: WorkflowContext[str]) -> None:
            out = llm_respond(prompt, str(text), agent_id=agent_key)
            await ctx.send_message(out)

    return AgentExec(id=node_id)

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from infrastructure_agent.ai_layer.ai_reasoning import AIReasoningLayer


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def create(self, **request):
        self.requests.append(deepcopy(request))
        return next(self.responses)


class FakeClient:
    def __init__(self, responses):
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


class FakeSSH:
    def __init__(self):
        self.calls = []

    async def execute_command(self, device_ip, command, *, approved=False):
        self.calls.append((device_ip, command, approved))
        return SimpleNamespace(
            to_dict=lambda: {
                "success": False,
                "stderr": "Destructive remote command requires explicit approval",
            }
        )


class EmptyDeployer:
    pass


class EmptyDiscovery:
    pass


def completion(content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls or []))
        ]
    )


def tool_call(name, arguments, call_id="call-1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


@pytest.mark.asyncio
async def test_openai_client_seam_runs_tool_then_continues_with_result():
    ssh = FakeSSH()
    client = FakeClient(
        [
            completion(
                tool_calls=[
                    tool_call(
                        "execute_ssh_command", {"device_ip": "10.0.0.2", "command": "rm -rf /tmp/x"}
                    )
                ]
            ),
            completion(content="The command was denied pending approval."),
        ]
    )
    layer = AIReasoningLayer(client=client)
    layer.model_id = "test-model"

    result = await layer.process_request("clean the device", EmptyDeployer(), ssh, EmptyDiscovery())

    assert result == "The command was denied pending approval."
    assert ssh.calls == [("10.0.0.2", "rm -rf /tmp/x", False)]
    assert len(client.chat.completions.requests) == 2
    assert client.chat.completions.requests[1]["messages"][-1]["role"] == "tool"
    assert client.chat.completions.requests[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_unknown_tool_is_returned_as_structured_failure():
    layer = AIReasoningLayer(client=FakeClient([]))
    layer.wire(EmptyDeployer(), FakeSSH(), EmptyDiscovery())

    result = await layer._dispatch_tool("not_a_tool", "{}")

    assert result == {"success": False, "error": "Unknown AI tool: not_a_tool"}


def test_tool_schema_does_not_expose_approval_as_model_control():
    tools = AIReasoningLayer._tool_definitions()
    ssh_tool = next(tool for tool in tools if tool["function"]["name"] == "execute_ssh_command")

    assert "approved" not in ssh_tool["function"]["parameters"]["properties"]
    assert "device_ip" in ssh_tool["function"]["parameters"]["required"]


def test_build_client_validates_configuration_without_network_call():
    layer = AIReasoningLayer(client=None)

    with pytest.raises(RuntimeError, match="AI model not configured"):
        layer._build_client()

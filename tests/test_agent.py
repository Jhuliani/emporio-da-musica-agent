"""Agent loop tests with a scripted fake LLM client (no network, no API key)."""

import json
from datetime import datetime
from types import SimpleNamespace

import openai
import pytest
from openai.types.chat import ChatCompletionMessage

from emporio.agent import FALLBACK_REPLY, Agent
from emporio.data import load_store
from emporio.llm import LLMConfig
from emporio.rules import STORE_TZ
from emporio.tools import StoreTools


def text_message(content):
    return ChatCompletionMessage(role="assistant", content=content)


def tool_message(name, arguments, call_id="call_1"):
    return ChatCompletionMessage.model_validate({
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)}}],
    })


class FakeClient:
    """Returns scripted messages (or raises scripted exceptions) in order."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(choices=[SimpleNamespace(message=item)])


@pytest.fixture
def make_agent(tmp_path):
    def _make(*script):
        tools = StoreTools(load_store(), now=lambda: datetime(2026, 11, 3, 10, tzinfo=STORE_TZ),
                           handoff_file=tmp_path / "handoffs.jsonl")
        config = LLMConfig(base_url="http://fake", model="fake-model", api_key="x")
        return Agent(config, tools=tools, client=FakeClient(*script))
    return _make


def test_plain_answer_without_tools(make_agent):
    agent = make_agent(text_message("Olá! Como posso ajudar?"))
    reply = agent.reply([], "oi")
    assert reply.text == "Olá! Como posso ajudar?"
    assert reply.tool_calls == []
    assert [m["role"] for m in reply.new_messages] == ["user", "assistant"]


def test_tool_call_result_is_sent_back_to_llm(make_agent):
    agent = make_agent(
        tool_message("get_product", {"name": "Takamine GD20"}),
        text_message("O Takamine GD20 custa R$ 2.199,00."),
    )
    reply = agent.reply([], "Quanto custa o Takamine GD20?")

    assert reply.tool_calls[0].name == "get_product"
    assert reply.tool_calls[0].result["price"] == 2199.0
    second_request = agent.client.requests[1]["messages"]
    tool_msg = second_request[-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
    assert json.loads(tool_msg["content"])["product_id"] == 95
    assert [m["role"] for m in reply.new_messages] == ["user", "assistant", "tool", "assistant"]


def test_system_prompt_includes_policies_and_current_date(make_agent):
    agent = make_agent(text_message("ok"))
    agent.reply([], "oi")
    system = agent.client.requests[0]["messages"][0]
    assert system["role"] == "system"
    assert "03/11/2026" in system["content"]
    assert "Direito de Arrependimento" in system["content"]


def test_history_is_forwarded(make_agent):
    agent = make_agent(text_message("ok"))
    history = [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "Olá!"}]
    agent.reply(history, "tudo bem?")
    assert agent.client.requests[0]["messages"][1:3] == history


def test_invalid_tool_arguments_do_not_crash(make_agent):
    bad = ChatCompletionMessage.model_validate({
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c", "type": "function",
                        "function": {"name": "get_product", "arguments": "{not json"}}],
    })
    agent = make_agent(bad, text_message("Pode repetir o nome do produto?"))
    reply = agent.reply([], "preço?")
    assert "error" in reply.tool_calls[0].result
    assert reply.text == "Pode repetir o nome do produto?"


def test_tool_round_limit(make_agent):
    agent = make_agent(*[tool_message("get_store_status", {}) for _ in range(10)])
    reply = agent.reply([], "loop")
    assert reply.text == FALLBACK_REPLY
    assert reply.error
    assert reply.new_messages == [{"role": "user", "content": "loop"}]


def test_authentication_error_is_reported(make_agent):
    # Built without __init__ to avoid depending on the SDK's HTTP response types.
    error = openai.AuthenticationError.__new__(openai.AuthenticationError)
    reply = make_agent(error).reply([], "oi")
    assert reply.text == FALLBACK_REPLY
    assert "Chave de API" in reply.error


def test_unbacked_handoff_claim_triggers_self_check(make_agent):
    agent = make_agent(
        text_message("Já registrei sua reclamação!"),  # claim without calling the tool
        tool_message("escalate_to_human", {"reason": "complaint", "summary": "Atendimento ruim"}),
        text_message("Sua reclamação foi registrada; a equipe responde em até 24 horas úteis."),
    )
    reply = agent.reply([], "Quero reclamar do atendimento")

    assert [c.name for c in reply.tool_calls] == ["escalate_to_human"]
    assert "24 horas" in reply.text
    saved = json.dumps(reply.new_messages, ensure_ascii=False)
    assert "Verificação automática" not in saved
    assert "Já registrei" not in saved


def test_handoff_claim_after_real_escalation_is_accepted(make_agent):
    agent = make_agent(
        tool_message("escalate_to_human", {"reason": "complaint", "summary": "x"}),
        text_message("Pronto, registrei sua reclamação."),
    )
    reply = agent.reply([], "Quero reclamar")
    assert reply.text == "Pronto, registrei sua reclamação."
    assert len(agent.client.requests) == 2


def test_empty_response_is_retried_once(make_agent):
    agent = make_agent(
        tool_message("get_store_status", {}),
        text_message(""),
        text_message("Estamos abertos!"),
    )
    reply = agent.reply([], "Estão abertos?")
    assert reply.text == "Estamos abertos!"
    assert reply.error is None


def test_repeated_empty_response_is_reported_as_error(make_agent):
    reply = make_agent(text_message(""), text_message("")).reply([], "oi")
    assert reply.text == FALLBACK_REPLY
    assert "vazia" in reply.error


def test_history_is_trimmed_at_turn_boundaries():
    from emporio.agent import trim_history

    history = []
    for i in range(12):
        history += [
            {"role": "user", "content": f"pergunta {i}"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "{}"},
            {"role": "assistant", "content": f"resposta {i}"},
        ]
    trimmed = trim_history(history, max_turns=8)
    assert trimmed[0] == {"role": "user", "content": "pergunta 4"}
    assert len(trimmed) == 8 * 4
    assert trim_history(history[:8], max_turns=8) == history[:8]

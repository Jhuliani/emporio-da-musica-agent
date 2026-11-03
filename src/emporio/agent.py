"""Agent loop: chat completions with function calling, written by hand.

No agent framework is used: the loop is ~50 lines, which keeps every tool call
visible (for the UI, logs and evals) and avoids framework lock-in.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

import openai

from emporio.data import load_store
from emporio.llm import LLMConfig
from emporio.prompt import build_system_prompt
from emporio.tools import StoreTools, normalize, tool_schemas

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
FALLBACK_REPLY = (
    "Desculpe, tive um problema técnico para responder agora. "
    "Você pode tentar de novo ou falar com a nossa equipe pelo WhatsApp (67) 3341-4444."
)
# "registrei", "encaminhei", "foi registrada"... (accent-insensitive)
HANDOFF_CLAIM = re.compile(r"\b(registrei|encaminhei|anotei|foi registrad\w*|foi encaminhad\w*)\b")
HANDOFF_NUDGE = (
    "[Verificação automática] Sua resposta diz que algo foi registrado ou encaminhado, mas "
    "`escalate_to_human` não foi chamada. Chame a ferramenta agora se for o caso, ou reescreva "
    "a resposta sem afirmar uma ação que não aconteceu."
)


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class AgentReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    new_messages: list[dict] = field(default_factory=list)  # to append to the history
    error: Optional[str] = None


class Agent:
    def __init__(self, config: LLMConfig, tools: Optional[StoreTools] = None, client=None):
        self.config = config
        self.tools = tools or StoreTools(load_store())
        self.schemas = tool_schemas(self.tools.store)
        self.client = client or config.client()

    def reply(self, history: list[dict], user_message: str) -> AgentReply:
        """Answer a user message given the previous conversation (OpenAI message format)."""
        new_messages: list[dict] = [{"role": "user", "content": user_message}]
        calls: list[ToolCall] = []
        system = {"role": "system", "content": build_system_prompt(self.tools.now())}
        correction_index: Optional[int] = None

        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[system, *history, *new_messages],
                    tools=self.schemas,
                    temperature=self.config.temperature,
                )
                message = response.choices[0].message

                if not message.tool_calls:
                    text = (message.content or "").strip() or FALLBACK_REPLY
                    if correction_index is None and self._claims_unperformed_handoff(text, history, calls):
                        # Self-check: the model said it registered/forwarded something
                        # without calling the tool. Ask it once to act or correct itself;
                        # the draft and the nudge are dropped from the saved history.
                        correction_index = len(new_messages)
                        new_messages += [{"role": "assistant", "content": text},
                                         {"role": "user", "content": HANDOFF_NUDGE}]
                        continue
                    if correction_index is not None:
                        del new_messages[correction_index:correction_index + 2]
                    new_messages.append({"role": "assistant", "content": text})
                    return AgentReply(text, calls, new_messages)

                # Keep the provider's raw tool_calls (some, like Gemini, attach
                # extra fields that must be sent back unchanged).
                new_messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [tc.model_dump(exclude_none=True) for tc in message.tool_calls],
                })
                for tc in message.tool_calls:
                    call = self._run_tool(tc.function.name, tc.function.arguments)
                    calls.append(call)
                    new_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(call.result, ensure_ascii=False, default=str),
                    })

            logger.warning("Tool round limit reached")
            return self._failure(new_messages, calls, "tool round limit reached")

        except openai.AuthenticationError:
            return self._failure(new_messages, calls, "Chave de API inválida ou sem permissão.")
        except openai.NotFoundError:
            return self._failure(new_messages, calls, f"Modelo '{self.config.model}' não encontrado neste provedor.")
        except openai.RateLimitError:
            return self._failure(new_messages, calls, "Limite de requisições do provedor atingido. Aguarde um pouco.")
        except openai.APIConnectionError:
            return self._failure(new_messages, calls, f"Não foi possível conectar a {self.config.base_url}.")
        except openai.InternalServerError:
            return self._failure(new_messages, calls,
                                 "Provedor indisponível ou sobrecarregado no momento. Tente novamente ou troque de modelo.")
        except openai.APIError as exc:
            logger.exception("LLM API error")
            return self._failure(new_messages, calls, f"Erro do provedor: {exc}")

    @staticmethod
    def _claims_unperformed_handoff(text: str, history: list[dict], calls: list[ToolCall]) -> bool:
        if not HANDOFF_CLAIM.search(normalize(text)):
            return False
        if any(c.name == "escalate_to_human" for c in calls):
            return False
        return not any(
            tc.get("function", {}).get("name") == "escalate_to_human"
            for m in history for tc in m.get("tool_calls") or []
        )

    def _run_tool(self, name: str, raw_arguments: str) -> ToolCall:
        try:
            arguments = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return ToolCall(name, {}, {"error": "Argumentos em JSON inválido."})
        result = self.tools.execute(name, arguments)
        logger.info("tool %s(%s) -> %s", name, arguments, "error" if "error" in result else "ok")
        return ToolCall(name, arguments, result)

    @staticmethod
    def _failure(new_messages: list[dict], calls: list[ToolCall], error: str) -> AgentReply:
        # Only the user message is kept, so a failed turn does not leave a
        # dangling tool call in the history.
        return AgentReply(FALLBACK_REPLY, calls, new_messages[:1], error=error)


if __name__ == "__main__":
    # Quick smoke test: python -m emporio.agent "Quanto custa o Takamine GD20?"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    question = " ".join(sys.argv[1:]) or "Qual o horário de funcionamento?"
    result = Agent(LLMConfig.from_env()).reply([], question)
    for c in result.tool_calls:
        print(f"[tool] {c.name}({c.arguments})")
    if result.error:
        print(f"[error] {result.error}")
    print(result.text)

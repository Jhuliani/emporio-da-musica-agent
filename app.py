"""Streamlit chat UI for the Empório da Música agent.

Run with:  streamlit run app.py

The API key typed in the sidebar lives only in this browser session's memory
(st.session_state): it is never written to disk, logs or the chat history.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from emporio.agent import Agent  # noqa: E402
from emporio.data import load_store  # noqa: E402
from emporio.llm import DEFAULT_PROVIDER, PROVIDER_PRESETS, LLMConfig  # noqa: E402
from emporio.tools import StoreTools  # noqa: E402

CUSTOM = "Personalizado"
WELCOME = (
    "Oi! Eu sou o Tom, assistente virtual da Empório da Música 🎸 "
    "Posso te ajudar com preços, disponibilidade de instrumentos, status de pedidos, "
    "formas de pagamento, trocas e muito mais. Como posso ajudar?"
)

st.set_page_config(page_title="Empório da Música — Atendimento", page_icon="🎸")


@st.cache_resource
def get_tools() -> StoreTools:
    return StoreTools(load_store())


def reset_conversation():
    st.session_state.history = [{"role": "assistant", "content": WELCOME}]
    st.session_state.display = [{"role": "assistant", "text": WELCOME, "tool_calls": []}]


def apply_preset():
    preset = PROVIDER_PRESETS.get(st.session_state.provider)
    if preset:
        st.session_state.base_url = preset["base_url"]
        st.session_state.model = preset["model"]


# --- Session state ------------------------------------------------------------

env_config = LLMConfig.from_env()
if "history" not in st.session_state:
    reset_conversation()
if "provider" not in st.session_state:
    st.session_state.provider = DEFAULT_PROVIDER
    st.session_state.base_url = env_config.base_url
    st.session_state.model = env_config.model

# --- Sidebar: provider settings -------------------------------------------------

with st.sidebar:
    st.header("⚙️ Modelo de linguagem")
    st.selectbox("Provedor", [*PROVIDER_PRESETS, CUSTOM], key="provider", on_change=apply_preset)
    st.text_input("Base URL (compatível com OpenAI)", key="base_url")
    st.text_input("Modelo", key="model")
    st.text_input(
        "API key",
        type="password",
        key="api_key",
        placeholder="usando LLM_API_KEY do .env" if env_config.api_key else "cole sua chave aqui",
    )
    st.caption("🔒 A chave fica só na memória desta sessão: não é salva em disco nem enviada a outro lugar.")
    key_url = PROVIDER_PRESETS.get(st.session_state.provider, {}).get("key_url")
    if key_url:
        st.caption(f"Obter chave: {key_url}")

    st.divider()
    show_tools = st.toggle("Mostrar chamadas de ferramentas", value=True)
    st.button("🗑️ Nova conversa", on_click=reset_conversation, use_container_width=True)

# --- Chat -------------------------------------------------------------------------

st.title("🎸 Empório da Música")
st.caption("Sua música começa aqui. · Atendimento virtual")


def render_tool_calls(tool_calls):
    if show_tools and tool_calls:
        with st.expander(f"🔧 {len(tool_calls)} chamada(s) de ferramenta"):
            for call in tool_calls:
                st.markdown(f"**`{call.name}`** `{call.arguments}`")
                st.json(call.result, expanded=False)


for entry in st.session_state.display:
    with st.chat_message(entry["role"]):
        render_tool_calls(entry["tool_calls"])
        st.markdown(entry["text"])

if prompt := st.chat_input("Digite sua mensagem..."):
    with st.chat_message("user"):
        st.markdown(prompt)

    api_key = st.session_state.api_key or env_config.api_key
    needs_key = st.session_state.provider != "Ollama (local)"
    if needs_key and not api_key:
        st.warning("Informe a API key na barra lateral para conversar com o agente.")
        st.stop()

    config = LLMConfig(base_url=st.session_state.base_url, model=st.session_state.model, api_key=api_key)
    agent = Agent(config, tools=get_tools())

    with st.chat_message("assistant"):
        with st.spinner("Tom está digitando..."):
            reply = agent.reply(st.session_state.history, prompt)
        render_tool_calls(reply.tool_calls)
        st.markdown(reply.text)
        if reply.error:
            st.error(f"Detalhe técnico: {reply.error}")

    st.session_state.history.extend(reply.new_messages)
    st.session_state.display.append({"role": "user", "text": prompt, "tool_calls": []})
    st.session_state.display.append({"role": "assistant", "text": reply.text, "tool_calls": reply.tool_calls})

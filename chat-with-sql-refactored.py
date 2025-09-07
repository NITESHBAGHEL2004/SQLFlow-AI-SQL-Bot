import os
import streamlit as st
from langchain.schema import AIMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from phi.agent.duckdb import DuckDbAgent

# ---------- Helper ----------
def get_avatar(path: str, fallback: str = "🤖") -> str:
    return path if os.path.exists(path) else fallback

# ---------- Initialize ----------
st.set_page_config(page_title="Conversational SQL Assistant", page_icon="🤖", layout="wide")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Sidebar for API Key
st.sidebar.markdown("## ⚙️ Settings")
st.sidebar.text_input("🔑 Gemini API Key", type="password", key="GeminiAPI")

# Get API key from sidebar
if not st.session_state.GeminiAPI:
    st.warning("⚠️ Please enter your Gemini API Key in the sidebar to continue.")
    llm = None
else:
    MODEL_NAME = "gemini-1.5-flash"
    llm = ChatGoogleGenerativeAI(model=MODEL_NAME, google_api_key=st.session_state.GeminiAPI)

# Initialize DuckDB Agent
agent = DuckDbAgent(path="data/mydb.duckdb", read_only=False)

# ---------- Functions ----------
def get_schema_text():
    tables_info = agent.run("SHOW TABLES;")
    schema_text = "Database Schema:\n"
    for table in tables_info:
        table_name = table[0] if isinstance(table, tuple) else table
        schema_text += f"\nTable: {table_name}\nColumns: "
        columns = agent.run(f"PRAGMA table_info('{table_name}');")
        column_names = [col[1] for col in columns]
        schema_text += ", ".join(column_names)
    return schema_text

def render_chat_messages():
    for message in st.session_state.chat_history:
        if isinstance(message, AIMessage):
            avatar = get_avatar("img/chatbot.png", "🤖")
            role = "assistant"
        else:
            avatar = get_avatar("img/boy.png", "👤")
            role = "user"
        with st.chat_message(role, avatar=avatar):
            st.markdown(message.content)

def handle_user_query(user_query: str):
    if not llm:
        st.error("❌ Gemini API Key not set. Please enter it in the sidebar.")
        return
    
    st.session_state.chat_history.append(HumanMessage(content=user_query))
    with st.chat_message("user", avatar=get_avatar("img/boy.png", "👤")):
        st.markdown(user_query)

    with st.chat_message("assistant", avatar=get_avatar("img/chatbot.png", "🤖")):
        try:
            schema_text = get_schema_text()
            sql_prompt = f"""
            You are an expert SQL assistant. You have the following database schema:

            {schema_text}

            Convert the following user request into a valid DuckDB SQL query.
            Do not explain, only return the SQL query.

            User request: {user_query}
            """
            sql_query = llm.invoke([HumanMessage(content=sql_prompt)]).content.strip()
            response = agent.run(sql_query)

            st.session_state.chat_history.append(AIMessage(content=str(response)))
            st.markdown(f"**📝 Generated SQL:** `{sql_query}`")
            st.markdown(f"**📊 Result:**\n\n{response}")

        except Exception as e:
            error_msg = f"⚠️ Error: {str(e)}"
            st.session_state.chat_history.append(AIMessage(content=error_msg))
            st.error(error_msg)

# ---------- UI ----------
st.title("🤖 Conversational SQL Assistant (Schema-Aware)")
render_chat_messages()

if user_query := st.chat_input("Ask me anything about your database..."):
    handle_user_query(user_query)

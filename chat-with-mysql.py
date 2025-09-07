import os
import streamlit as st
import pandas as pd
import mysql.connector
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_community.utilities import SQLDatabase
from langchain_google_genai import GoogleGenerativeAI

# --- Prompts ---
SQL_QUERY_PROMPT = """
You are a SQL assistant. Based on the schema below, write a SQL query to answer the user's question.
Return the full SQL query only, nothing else. You can generate any type of query: SELECT, SHOW, INSERT, UPDATE, DELETE, DESCRIBE, EXPLAIN, etc.

<SCHEMA>{schema}</SCHEMA>
Conversation History: {chat_history}

User Request: {question}
SQL Query:
"""

NATURAL_RESPONSE_PROMPT = """
You are a data analyst. Write a natural language answer based on:
Schema: {schema}
Conversation History: {chat_history}
User Question: {question}
SQL Query: {query}
SQL Response: {response}

Answer:
"""

NATURAL_ACTION_RESPONSE_PROMPT = """
You are a SQL assistant. Explain the result of a non-SELECT SQL query (INSERT, UPDATE, DELETE, etc.) in simple natural language.
SQL Query: {query}
Execution Result: {result}

Explanation:
"""

ERROR_EXPLANATION_PROMPT = """
You are a database expert. The following query failed. Explain why and how to fix it.
SQL Query: {query}
Error: {error}
Explanation:
"""

# --- Database Functions ---
def init_database(user: str, password: str, host: str, port: str, database: str) -> SQLDatabase:
    uri = f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}"
    return SQLDatabase.from_uri(uri)

def run_dict_query(user: str, password: str, host: str, port: str, database: str, query: str):
    conn = mysql.connector.connect(
        host=host, user=user, password=password, port=port, database=database
    )
    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(query)
        if query.strip().lower().startswith(("select", "show", "describe", "explain")):
            result = cursor.fetchall()
        else:
            conn.commit()
            result = {"rows_affected": cursor.rowcount}
    conn.close()
    return result

# --- LangChain Chains ---
def get_sql_chain(db: SQLDatabase):
    prompt = ChatPromptTemplate.from_template(SQL_QUERY_PROMPT)
    return (
        RunnablePassthrough.assign(schema=lambda _: db.get_table_info())
        | prompt
        | LLM
        | StrOutputParser()
    )

def get_response(user_query: str, db: SQLDatabase, chat_history: list, sql_query: str, response: list):
    prompt = ChatPromptTemplate.from_template(NATURAL_RESPONSE_PROMPT)
    return (
        RunnablePassthrough.assign(schema=lambda _: db.get_table_info())
        | prompt
        | LLM
        | StrOutputParser()
    ).invoke({
        "question": user_query,
        "chat_history": chat_history,
        "query": sql_query,
        "response": response,
    })

def explain_sql_action(sql_query: str, result):
    """Explain INSERT/UPDATE/DELETE/other non-SELECT results in natural language."""
    prompt = ChatPromptTemplate.from_template(NATURAL_ACTION_RESPONSE_PROMPT)
    return (
        RunnablePassthrough.assign(query=lambda _: sql_query, result=lambda _: result)
        | prompt
        | LLM
        | StrOutputParser()
    ).invoke({
        "query": sql_query,
        "result": result
    })

def explain_sql_error(sql_query: str, error: str):
    prompt = ChatPromptTemplate.from_template(ERROR_EXPLANATION_PROMPT)
    return (
        RunnablePassthrough.assign(query=lambda _: sql_query, error=lambda _: error)
        | prompt
        | LLM
        | StrOutputParser()
    ).invoke({
        "language": "English"
    })

# --- Sidebar Config ---
def sidebar_config():
    st.sidebar.markdown("## ⚙️ Settings")

    # 🔑 Gemini API Key (added here)
    st.sidebar.text_input("🔑 Gemini API Key", type="password", key="GeminiAPI")

    st.sidebar.text_input("Host", value="localhost", key="Host")
    st.sidebar.text_input("Port", value="3306", key="Port")
    st.sidebar.text_input("User", value="root", key="User")
    st.sidebar.text_input("Password", type="password", value="", key="Password")
    st.sidebar.text_input("Database", value=" ", key="Database")
    
    if st.sidebar.button("Connect"):
        try:
            with st.spinner("Connecting to database..."):
                db = init_database(
                    st.session_state["User"],
                    st.session_state["Password"],
                    st.session_state["Host"],
                    st.session_state["Port"],
                    st.session_state["Database"]
                )
                st.session_state.db = db
                st.success("✅ Connected to database!")
        except Exception as e:
            st.error(f"❌ Connection failed: {str(e)}")
           
    st.sidebar.markdown("🤖 Crafted By Nitesh Singh 🤖")

# --- Chat UI ---
def render_chat_messages():
    for message in st.session_state.chat_history:
        role = "ai" if isinstance(message, AIMessage) else "human"
        avatar = "🤖" if role == "ai" else "👤"
        with st.chat_message(role, avatar=avatar):
            st.markdown(message.content)

def handle_user_query(user_query: str):
    st.session_state.chat_history.append(HumanMessage(content=user_query))
    with st.chat_message("human", avatar="👤"):
        st.markdown(user_query)

    with st.chat_message("ai", avatar="🤖"):
        try:
            sql_chain = get_sql_chain(st.session_state.db)
            sql_query = sql_chain.invoke({
                "chat_history": st.session_state.chat_history,
                "question": user_query
            }).strip()

            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

            result = run_dict_query(
                st.session_state["User"],
                st.session_state["Password"],
                st.session_state["Host"],
                st.session_state["Port"],
                st.session_state["Database"],
                sql_query
            )

            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                df = pd.DataFrame(result)
                if not df.empty:
                    st.markdown("### 📊 Query Result:")
                    st.dataframe(df)
                else:
                    st.info("Query executed successfully. No rows returned.")
                response = get_response(user_query, st.session_state.db, st.session_state.chat_history, sql_query, result)
            else:
                st.info(f"Query executed successfully. {result.get('rows_affected', 0)} rows affected.")
                response = explain_sql_action(sql_query, result)

            st.markdown("### 🛠️ Generated SQL Query:")
            st.code(sql_query, language="sql")

            st.markdown("### 💬 AI Response:")
            st.markdown(response)

            st.session_state.chat_history.extend([
                AIMessage(content=f"SQL Query: {sql_query}"),
                AIMessage(content=response)
            ])
        except Exception as e:
            error_message = explain_sql_error(user_query, str(e))
            st.error("❌ An error occurred while processing the query.")
            st.markdown("### ❗ Error explanation:")
            st.markdown(error_message)
            st.session_state.chat_history.append(AIMessage(content=error_message))

# --- Run App ---
st.set_page_config(page_title="Chat with MySQL + Gemini", page_icon="🤖")
st.title("🤖 SQLFlow – AI SQL Bot")

sidebar_config()

# ✅ Use user-provided Gemini API key
if "GeminiAPI" in st.session_state and st.session_state.GeminiAPI.strip():
    LLM = GoogleGenerativeAI(
        model="gemini-1.5-flash",
        api_key=st.session_state.GeminiAPI
    )
else:
    LLM = None
    st.warning("⚠️ Please enter your Gemini API Key in the sidebar to continue.")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        AIMessage(content="Hello! I'm a SQL assistant. Ask me anything about your database.")
    ]

if "db" in st.session_state and LLM:
    render_chat_messages()
    user_input = st.chat_input("Ask anything about your database...")
    if user_input and user_input.strip():
        handle_user_query(user_input)

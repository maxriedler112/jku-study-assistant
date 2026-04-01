import streamlit as st
from assistant import ask_assistant

st.set_page_config(page_title="JKU Study Assistant", page_icon="🎓")

st.title("🎓 JKU Wirtschaftsinformatik Guide")
st.markdown("Frag mich alles zum Curriculum!")

# Chat Historie initialisieren
if "messages" not in st.session_state:
    st.session_state.messages = []

# Alte Nachrichten anzeigen
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Benutzereingabe
if prompt := st.chat_input("Deine Frage zum Studium..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Antwort generieren
    with st.chat_message("assistant"):
        with st.spinner("Ich lese im Curriculum nach..."):
            response = ask_assistant(prompt)
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})
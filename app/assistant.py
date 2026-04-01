import os
from dotenv import load_dotenv
from groq import Groq
from search import search_jku_knowledge

load_dotenv()

# Setup Groq Client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def ask_assistant(question: str):
    # 1. Relevante Informationen aus Supabase holen
    print("🔍 Suche in den JKU-Dokumenten...")
    context_results = search_jku_knowledge(question)
    
    # Den gefundenen Text zu einem großen Block zusammenfügen
    context_text = "\n\n".join([res['content'] for res in context_results])
    
    # 2. System-Prompt erstellen (Die "Regeln" für die KI)
    system_prompt = f"""
    Du bist ein hilfreicher Studien-Assistent für die JKU (Johannes Kepler Universität).
    Nutze NUR den unten stehenden Kontext, um die Frage des Nutzers zu beantworten.
    Wenn die Antwort nicht im Kontext steht, sage höflich, dass du das nicht weißt.
    Beantworte die Frage präzise und freundlich.

    KONTEXT:
    {context_text}
    """

    # 3. Anfrage an die KI (Llama 3 über Groq)
    print("🤖 Generiere Antwort...")
    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        model="llama-3.1-8b-instant", # Ein sehr schnelles und fähiges Modell
        temperature=0.2,         # Niedrige Temperatur für faktenbasierte Antworten
    )

    return chat_completion.choices[0].message.content

if __name__ == "__main__":
    user_frage = input("Deine Frage an den JKU-Assistenten: ")
    antwort = ask_assistant(user_frage)
    
    print("\n" + "="*50)
    print("JKU ASSISTENT:")
    print(antwort)
    print("="*50)
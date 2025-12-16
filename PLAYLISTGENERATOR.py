import streamlit as st
from huggingface_hub import InferenceClient
import requests
import random
import os                     # <--- НУЖНО для работы с системой
from dotenv import load_dotenv # <--- НУЖНО для чтения .env файла

# --- ИНИЦИАЛИЗАЦИЯ ОКРУЖЕНИЯ ---
# Эта команда ищет файл .env и загружает из него переменные
load_dotenv()

# Пробуем получить токен из .env. Если его нет, вернется None.
# "HF_TOKEN" должно совпадать с названием переменной внутри файла .env
ENV_TOKEN = os.getenv("HF_TOKEN")

# Если токен нашелся в .env, используем его как значение по умолчанию.
# Если нет — оставляем пустую строку.
DEFAULT_VALUE = ENV_TOKEN if ENV_TOKEN else ""

# --- КОНФИГУРАЦИЯ МОДЕЛИ ---
MODEL_REPO_ID = "Qwen/Qwen2.5-72B-Instruct"

# --- BACKEND: СЕРВИС ПОЛУЧЕНИЯ ДАННЫХ ---
def fetch_artist_metadata(artist_name: str) -> dict | None:
    """
    Получает метаданные артиста через API Deezer.
    """
    try:
        # 1. Поиск ID артиста
        search_url = f"https://api.deezer.com/search/artist?q={artist_name}"
        response = requests.get(search_url).json()
        
        if not response.get('data'):
            return None
            
        artist_obj = response['data'][0]
        artist_id = artist_obj['id']
        real_name = artist_obj['name']
        
        # 2. Топ-треки
        tracks_url = f"https://api.deezer.com/artist/{artist_id}/top?limit=4"
        tracks_data = requests.get(tracks_url).json().get('data', [])
        source_tracks = [t['title'] for t in tracks_data]
        
        # 3. Похожие исполнители (с запасом для рандома)
        related_url = f"https://api.deezer.com/artist/{artist_id}/related?limit=20"
        related_data_all = requests.get(related_url).json().get('data', [])
        
        # Случайная выборка 5 похожих
        if len(related_data_all) > 5:
            related_data = random.sample(related_data_all, 5)
        else:
            related_data = related_data_all
        
        similar_artists_info = []
        for rel_artist in related_data:
            r_id = rel_artist['id']
            r_tracks_url = f"https://api.deezer.com/artist/{r_id}/top?limit=2"
            r_tracks_data = requests.get(r_tracks_url).json().get('data', [])
            r_tracks = [t['title'] for t in r_tracks_data]
            
            similar_artists_info.append({
                "name": rel_artist['name'],
                "tracks": r_tracks
            })
            
        return {
            "source_artist": real_name,
            "source_tracks": source_tracks,
            "similar": similar_artists_info
        }
    except Exception as e:
        print(f"API Error: {e}")
        return None

# --- КЛАСС АГЕНТА ---
class Agent:
    def __init__(self, name: str, role: str, client: InferenceClient):
        self.name = name
        self.role = role
        self.client = client

    def execute(self, input_context: str) -> str:
        messages = [
            {
                "role": "system", 
                "content": f"""
                РОЛЬ: {self.name}
                ЗАДАЧА: {self.role}
                ОГРАНИЧЕНИЯ: Русский язык, Markdown разметка, работа строго по контексту.
                """
            },
            {
                "role": "user", 
                "content": f"КОНТЕКСТ ДАННЫХ:\n{input_context}"
            }
        ]
        try:
            response = self.client.chat_completion(
                messages=messages, max_tokens=1500, temperature=0.4, top_p=0.9
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Ошибка выполнения агента: {e}"

# --- ИНТЕРФЕЙС (STREAMLIT) ---
def main():
    st.set_page_config(page_title="Интеллектуальная МАС", page_icon="🎵", layout="wide")
    
    st.title("🎵 Интеллектуальная Система Генерации Плейлистов")
    st.markdown("### Лабораторная работа: Мультиагентные системы")
    st.markdown("**Выполнили:** Грудницкий и Соловьёв")
    st.markdown("---")

    with st.sidebar:
        st.header("Конфигурация Системы")
        
        # ВАЖНО: value=DEFAULT_VALUE автоматически подставит токен из .env
        hf_token = st.text_input("Токен Hugging Face API", value=DEFAULT_VALUE, type="password")
        
        if not hf_token:
            st.warning("Ожидание токена авторизации...")
            return

    # Инициализация клиента нейросети
    client = InferenceClient(model=MODEL_REPO_ID, token=hf_token)

    col1, col2 = st.columns([3, 1])
    with col1:
        user_query = st.text_input("Ввод Исполнителя / Референс", "Linkin Park")
    with col2:
        st.write("")
        st.write("")
        run_btn = st.button("Инициализировать Агентов", type="primary")

    if run_btn and user_query:
        
        # --- ЭТАП 0: СБОР ДАННЫХ ---
        raw_data = None
        with st.status("Система: Получение метаданных из внешнего API...", expanded=True) as status:
            raw_data = fetch_artist_metadata(user_query)
            if raw_data:
                st.success(f"Целевой объект идентифицирован: {raw_data['source_artist']}.")
                status.update(label="Сбор данных завершен", state="complete")
            else:
                status.update(label="Ошибка сбора данных", state="error")
                st.error("Исполнитель не найден.")
                st.stop()

        context_payload = f"ЦЕЛЕВАЯ СУЩНОСТЬ: {raw_data['source_artist']} (Топ-треки: {', '.join(raw_data['source_tracks'])})\n"
        context_payload += "СВЯЗАННЫЕ СУЩНОСТИ:\n"
        for s in raw_data['similar']:
            context_payload += f"- {s['name']} (Треки: {', '.join(s['tracks'])})\n"

        st.divider()

        # --- ЭТАП 1: АНАЛИЗ ---
        st.subheader("🕵️ Агент 1: Семантический Анализ")
        agent1 = Agent(
            name="Агент 1 (Анализатор Сходства)",
            role="Проанализируй список связанных исполнителей. Объясни стилистические связи между целевым артистом и связанными сущностями.",
            client=client
        )
        with st.chat_message("assistant", avatar="🕵️"):
            with st.spinner("Выполнение семантического анализа..."):
                output_1 = agent1.execute(context_payload)
                st.markdown(output_1)

        # --- ЭТАП 2: АГРЕГАЦИЯ ---
        st.subheader("💿 Агент 2: Агрегация Плейлиста")
        agent2 = Agent(
            name="Агент 2 (Композитор Плейлиста)",
            role="Сформируй единый список треков на основе контекста. Формат: 'Исполнитель - Трек'. Не генерируй несуществующие данные.",
            client=client
        )
        with st.chat_message("assistant", avatar="💿"):
            with st.spinner("Компиляция списка треков..."):
                output_2 = agent2.execute(context_payload)
                st.markdown(output_2)

        # --- ЭТАП 3: КЛАСТЕРИЗАЦИЯ ---
        st.subheader("📊 Агент 3: Кластеризация по Настроению")
        agent3 = Agent(
            name="Агент 3 (Классификатор)",
            role="Раздели список на две контрастные категории настроения. Выведи отсортированные списки под заголовками.",
            client=client
        )
        with st.chat_message("assistant", avatar="📊"):
            with st.spinner("Классификация аудио-признаков..."):
                output_3 = agent3.execute(output_2)
                st.markdown(output_3)

        # --- ЭТАП 4: РЕКОМЕНДАЦИИ ---
        st.subheader("🟢 Агент 4: Рекомендательная Система")
        agent4 = Agent(
            name="Агент 4 (Discovery Engine)",
            role="""
            1. Предложи 3 НОВЫХ трека от других исполнителей (которых нет в списке).
            """,
            client=client
        )
        with st.chat_message("assistant", avatar="🟢"):
            with st.spinner("Генерация рекомендаций..."):
                output_4 = agent4.execute(output_3)
                st.success("Альтернативные Миксы и Discovery:")
                st.markdown(output_4)

if __name__ == "__main__":
    main()
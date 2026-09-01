import os
import json
import requests
import urllib.parse
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

# Configurations
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PROCESSED_JOBS_FILE = "processed_jobs.json"

TARGET_LOCATION = "Fortaleza, Ceará, Brasil"
PROFILE_TARGET = "Analista (Jr, Pleno, Processos, Dados, Projetos, Operacional)"
NEGATIVE_KEYWORDS = "Estágio, Desenvolvedor Senior"

SEARCH_TERMS = ["Analista", "Analista de Processos", "Analista de Dados"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# --- NOVAS FONTES: INDEED & CATHO ---

def fetch_indeed_jobs(term):
    jobs = []
    try:
        encoded_term = urllib.parse.quote(term)
        encoded_location = urllib.parse.quote(TARGET_LOCATION)
        url = f"https://br.indeed.com/rss?q={encoded_term}&l={encoded_location}"
        
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "xml")
            items = soup.find_all("item")
            for item in items:
                title = item.find("title").text if item.find("title") else "Sem título"
                link = item.find("link").text if item.find("link") else ""
                desc = item.find("description").text if item.find("description") else ""
                
                jobs.append({
                    "id": f"indeed_{link}",
                    "title": title,
                    "company": "Indeed",
                    "link": link,
                    "description": desc,
                    "source": "Indeed"
                })
    except Exception as e:
        print(f"Aviso Indeed ({term}): {e}")
    return jobs

def fetch_catho_jobs(term):
    jobs = []
    try:
        url = f"https://www.catho.com.br/vagas/api/v1/vagas?q={urllib.parse.quote(term)}&cidade={urllib.parse.quote(TARGET_LOCATION)}&limit=10"
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for v in data.get("vagas", []):
                jobs.append({
                    "id": f"catho_{v.get('id')}",
                    "title": v.get("titulo", ""),
                    "company": v.get("contratante", {}).get("nome", "Confidencial"),
                    "link": f"https://www.catho.com.br/vagas/vaga/{v.get('id')}",
                    "description": v.get("descricao", ""),
                    "source": "Catho"
                })
    except Exception as e:
        print(f"Aviso Catho ({term}): {e}")
    return jobs

# --- FILTRAGEM COM IA ---

def is_job_relevant_with_ai(job_title, job_description):
    if not GEMINI_API_KEY:
        return True, "Sem API Key"

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"""
        Avalie se a vaga é RELEVANTE para o perfil.
        Perfil Desejado: {PROFILE_TARGET}
        Região Preferencial: {TARGET_LOCATION} ou Remoto
        Filtro Negativo: {NEGATIVE_KEYWORDS}

        Vaga: {job_title}
        Descrição: {job_description}

        Responda APENAS em JSON estrito:
        {{"relevant": true, "reason": "motivo curto em ate 6 palavras"}}
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
        )
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text_resp)
        return data.get("relevant", False), data.get("reason", "Aprovado")
    except Exception as e:
        return False, f"Descartado por erro/timeout na IA: {e}"

# --- NOTIFICAÇÃO & EXECUÇÃO ---

def send_telegram(job, reason):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    msg = f"🎯 <b>Nova Vaga ({job['source']})!</b>\n\n📌 <b>Cargo:</b> {job['title']}\n🏢 <b>Empresa:</b> {job['company']}\n💡 <b>IA:</b> {reason}\n\n🔗 <a href='{job['link']}'>Ver Vaga</a>"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception:
        pass

def main():
    processed = load_processed_jobs()
    all_jobs = []

    for term in SEARCH_TERMS:
        all_jobs.extend(fetch_linkedin_jobs(term))
        all_jobs.extend(fetch_vagas_com_jobs(term))
        all_jobs.extend(fetch_gupy_jobs(term))
        all_jobs.extend(fetch_indeed_jobs(term))
        all_jobs.extend(fetch_catho_jobs(term))

    print(f"Total de vagas encontradas: {len(all_jobs)}")

    for job in all_jobs:
        if job["id"] in processed:
            continue

        relevant, reason = is_job_relevant_with_ai(job["title"], job["description"])
        if relevant:
            print(f"[APROVADA] {job['title']} - {job['source']}")
            send_telegram(job, reason)
        else:
            print(f"[REJEITADA] {job['title']} - Motivo: {reason}")

        processed.add(job["id"])

    save_processed_jobs(processed)
    print("Execução concluída com sucesso!")

if __name__ == "__main__":
    main()

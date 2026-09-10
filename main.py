import os
import json
import requests
import urllib.parse
from google import genai
from google.genai import types

# Configurations
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
PROCESSED_JOBS_FILE = "processed_jobs.json"

TARGET_LOCATION = "Fortaleza, Ceará, Brazil"
PROFILE_TARGET = "Analista (Jr, Pleno, Processos, Dados, Projetos, Operacional, Sistemas)"
NEGATIVE_KEYWORDS = "Estágio, Desenvolvedor Senior"

SEARCH_TERMS = ["Analista", "Analista de Processos", "Analista de Dados"]

# --- GERENCIAMENTO DO HISTÓRICO ---

def load_processed_jobs():
    if os.path.exists(PROCESSED_JOBS_FILE):
        try:
            with open(PROCESSED_JOBS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return set(json.loads(content)) if content else set()
        except Exception:
            return set()
    return set()

def save_processed_jobs(processed_jobs):
    try:
        with open(PROCESSED_JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(processed_jobs), f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Erro ao salvar histórico: {e}")

# --- BUSCA UNIFICADA DE VAGAS VIA SERPAPI (GOOGLE JOBS) ---

def fetch_google_jobs(term):
    jobs = []
    if not SERPAPI_KEY:
        print("Aviso: SERPAPI_KEY não configurada!")
        return jobs

    try:
        params = {
            "engine": "google_jobs",
            "q": f"{term} em {TARGET_LOCATION}",
            "hl": "pt-br",
            "gl": "br",
            "api_key": SERPAPI_KEY
        }
        response = requests.get("https://serpapi.com/search", params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            results = data.get("jobs_results", [])
            for item in results:
                job_id = item.get("job_id") or item.get("docid") or item.get("link", "")
                title = item.get("title", "Sem título")
                company = item.get("company_name", "Confidencial")
                description = item.get("description", f"Vaga para {title}")
                
                # Obtém o link direto para candidatura ou portal da vaga
                link = ""
                apply_options = item.get("apply_options", [])
                if apply_options:
                    link = apply_options[0].get("link", "")
                if not link:
                    link = item.get("share_link", "")

                # Identifica a fonte (LinkedIn, Catho, Indeed, Vagas.com, etc)
                via = item.get("via", "Google Jobs").replace("via ", "")

                jobs.append({
                    "id": f"serp_{job_id}",
                    "title": title,
                    "company": company,
                    "link": link,
                    "description": description[:1000],  # Limita tamanho para a IA
                    "source": via
                })
        else:
            print(f"Erro SerpApi ({term}): Status {response.status_code}")
    except Exception as e:
        print(f"Erro ao buscar via SerpApi ({term}): {e}")
    
    return jobs

# --- FILTRAGEM COM IA (GEMINI) ---

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

        Responda APENAS em JSON estrito com as chaves: "relevant" (boolean) e "reason" (string de ate 6 palavras).
        Exemplo: {{"relevant": true, "reason": "Perfil de analista compativel"}}
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text_resp)
        return bool(data.get("relevant", False)), str(data.get("reason", "Aprovado"))
    except Exception as e:
        return True, "Aprovado via Fallback"

# --- NOTIFICAÇÃO TELEGRAM ---

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
    except Exception as e:
        print(f"Erro Telegram: {e}")

# --- EXECUÇÃO PRINCIPAL ---

def main():
    processed = load_processed_jobs()
    all_jobs = []

    for term in SEARCH_TERMS:
        jobs = fetch_google_jobs(term)
        all_jobs.extend(jobs)

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
